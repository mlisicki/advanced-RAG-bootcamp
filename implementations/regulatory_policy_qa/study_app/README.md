# Regulatory QA study app

From the repository root, run:

```bash
./implementations/regulatory_policy_qa/study_app/start.sh
```

Open http://127.0.0.1:8765. No dependencies or API key are needed. Each session has independent review and answer timers for all 20 questions. Switching questions or hiding the tab pauses the active timer; returning resumes it. Review ends when its timer expires or you start answering, and answering locks when its timer expires. Use New session to take the test again; previous sessions remain available in the session selector.

New sessions shuffle all 20 questions and retain that order when resumed. Sessions created before shuffling was added keep their original order.

If the port is already in use, add `--port 8766` to the command and open http://127.0.0.1:8766 instead.

Answers and remaining time are saved automatically to timestamped session records in `sessions/`, which is ignored by Git. The app also keeps a browser backup. Keep the local server running while studying; a save error is shown if it becomes unavailable. These are practice timers, not a secure exam environment.

The reading passages are drawn from the repository notebooks, starting with the section most relevant to each question and extending into nearby sections up to 1,500 words (roughly 10 minutes of careful technical reading). Source links open notebook prose during review. Short notebooks may have less material. The app does not grade answers.
