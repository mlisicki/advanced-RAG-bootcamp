#!/usr/bin/env python3
"""Local, dependency-free study server. Run with python3 server.py."""

import argparse
import json
import os
import re
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
RI = HERE.parent
DATA = HERE / "sessions"
QUESTIONS = [
    ("What corpus, question population, chunking setup, and retrieval scope define the CUAD baseline?", "01", 0),
    (
        "Define retrieval failure and MRR. Give an example where MRR improves while retrieval failure stays unchanged.",
        "01",
        1,
    ),
    (
        "Why is shuffled retrieval included as a negative control? What does outperforming it prove, and what does it not prove?",
        "01",
        1,
    ),
    (
        "Why are null-question abstention metrics evaluated separately from answerable-question retrieval metrics? Why is always abstaining inadequate?",
        "01",
        3,
    ),
    (
        "Why is comparing chunk sizes at a fixed k confounded? What control is introduced, and what reversal is observed when text budget is matched?",
        "01",
        4,
    ),
    (
        "What changed between the two dense BGE baseline configurations, and why does RUN_EXPENSIVE=False still allow their comparison?",
        "01",
        2,
    ),
    (
        "Write the weighted RRF contribution for a chunk at rank r. Why was the shipped BM25/dense weight selected on CUAD-all rather than a 20-document slice?",
        "02",
        4,
    ),
    ("Why does ContractNLI report retrieval failure at k=3 while CUAD uses k=10?", "02", 2),
    (
        "What does SPLADE represent differently from dense retrieval and ColBERT? Why can a reranker make a strong SPLADE first stage worse?",
        "02",
        3,
    ),
    (
        "Why report agreement with exact rankings in addition to failure and MRR in the Qdrant experiment? What does the small collection size imply for HNSW and quantization latency?",
        "02",
        8,
    ),
    (
        "Which chunking variants change only embed_text, and which requires rebuilding relevance judgments? Why?",
        "03",
        2,
    ),
    (
        "Why does contextual chunking help dramatically for unscoped ContractNLI retrieval but not for retrieval already scoped to one contract?",
        "03",
        5,
    ),
    (
        "Why did the full-document contextual prompt initially underperform the cheaper head-and-neighbourhood prompt, and what instruction substantially changed that result?",
        "03",
        6,
    ),
    (
        "How does notebook 04 construct a synthetic evaluation set with gold evidence offsets and null questions from an unlabeled document folder?",
        "04",
        1,
    ),
    (
        "What are the main limitations of using notebook 04's generated questions to select a retrieval arm? What does a paired bootstrap interval containing zero mean?",
        "04",
        2,
    ),
    (
        "Describe the recommended single-pass answering configuration in notebook 07: retrieval, passage counts, abstention, and separate answer judgments.",
        "07",
        1,
    ),
    (
        "In notebook 05, what is the difference between deterministic template cleanup and feedback-driven corrective rewriting? Which comparison isolates citation validation without a second generation sample?",
        "05",
        3,
    ),
    (
        "Why can an answer be grounded yet incorrect for the task? How does the unscoped control demonstrate this, and why is a retry-versus-resampling control necessary?",
        "05",
        7,
    ),
    (
        "What do RAGAS faithfulness, answer relevancy, and semantic similarity measure? Why should none be treated as benchmark accuracy in the notebook's fixture?",
        "06",
        4,
    ),
    (
        "Why is binding search scope alone insufficient protection in the starter agent? Explain isolated indexes, audited tool traces, model-call limits, and the difference between a budget stop and abstention.",
        "99",
        2,
    ),
]


def materials(prefix, section):
    """Extract a bounded reading passage from the selected notebook section."""
    path = next(RI.glob(prefix + "_*.ipynb"))
    notebook = json.loads(path.read_text())
    sections, current = [], []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "markdown":
            continue
        text = "".join(cell["source"])
        if text.startswith("## ") and current:
            sections.append("\n\n".join(current))
            current = []
        current.append(text)
    if current:
        sections.append("\n\n".join(current))
    # Start with the relevant section, then nearby sections for context.
    order = [section] + list(range(section + 1, len(sections))) + list(range(section - 1, -1, -1))
    words = "\n\n".join(sections[i] for i in order if 0 <= i < len(sections)).split()
    # Preserve paragraphs and sentence boundaries while limiting reading load.
    text = "\n\n".join(sections[i] for i in order if 0 <= i < len(sections))
    if len(words) > 1500:
        matches = list(re.finditer(r"\S+", text))
        cut = matches[1499].end()
        end = text.rfind(". ", 0, cut)
        text = text[: end + 1] if end > cut // 2 else text[:cut] + "…"
    return {"text": text, "source": path.name, "words": min(len(words), 1500)}


class Handler(BaseHTTPRequestHandler):
    """Serve study materials and persist local practice sessions."""

    def send(self, status, data, kind="application/json; charset=utf-8"):
        """Send an uncached response with the given status and content type."""
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Serve the UI, questions, notebook prose, or saved sessions."""
        path = urlparse(self.path).path
        if path == "/":
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/questions":
            return self.send(200, [{"question": q, **materials(n, s)} for q, n, s in QUESTIONS])
        if path == "/api/sessions":
            DATA.mkdir(exist_ok=True)
            return self.send(200, [json.loads(p.read_text()) for p in sorted(DATA.glob("*.json"), reverse=True)])
        if path.startswith("/source/"):
            name = path.removeprefix("/source/")
            if name in [p.name for p in RI.glob("*.ipynb")]:
                notebook = json.loads((RI / name).read_text())
                content = "\n\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "markdown")
                return self.send(200, content.encode(), "text/plain; charset=utf-8")
        return self.send(404, {"error": "Not found"})

    def do_POST(self):
        """Validate a session identifier and atomically save its record."""
        if self.path != "/api/session":
            return self.send(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 2_000_000:
                raise ValueError("Session too large")
            data = json.loads(self.rfile.read(length))
            uuid.UUID(data["id"])
            if not re.fullmatch(r"[0-9a-f-]{36}", data["id"]):
                raise ValueError("Invalid session ID")
            data["savedAt"] = datetime.now(timezone.utc).isoformat()
            DATA.mkdir(exist_ok=True)
            target = DATA / (data["id"] + ".json")
            temp = DATA / (data["id"] + "." + uuid.uuid4().hex + ".tmp")
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            os.replace(temp, target)
            self.send(200, {"savedAt": data["savedAt"]})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
            self.send(400, {"error": str(error)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Study app: http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
    server.serve_forever()
