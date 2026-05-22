---
name: fork
description: Launches an isolated subagent to investigate a bug, review code, or explore an area without polluting main-conversation context. Use when the task would otherwise load large stack traces, diffs, or exploratory reads into your main context.
---

# /fork

Run an isolated task in a subagent. Main context stays clean; only the agent's structured result comes back.

## Usage

```
/fork debug   <bug summary or error + relevant paths>
/fork review  <PR number, branch, or file list>
/fork explore <question + area of the codebase>
```

Scope determines the agent's instructions. If no scope is given, ask the user to pick one.

## Steps

1. **Capture scope** — one of:
   - `debug`: 2-3 sentence bug summary (expected vs. actual + where it manifests).
   - `review`: what to review (PR / branch / file list) + focus areas.
   - `explore`: the question + the area of the codebase that likely contains the answer.

2. **Launch subagent** — Use the Task tool with `subagent_type: "general-purpose"` and `model: "sonnet"`. Pass only the summary + relevant paths. Do NOT paste file contents — the agent reads them.

   **Debug instructions:**
   > Investigate this bug. Read the relevant files, trace the issue, and return: (1) root cause, (2) fix with exact file paths and line numbers, (3) verification command.

   **Review instructions:**
   > Review this code for correctness, security, performance, and style. Return findings as a structured list: severity (critical/warning/note), file path, line number, recommendation.

   **Explore instructions:**
   > Answer this question by reading the relevant code. Return: (1) direct answer, (2) file paths + line numbers supporting it, (3) any caveats or follow-up questions.

3. **Receive results** — the subagent returns a structured report without dumping intermediate reads into main context.

4. **Act on the report** — apply the fix, address findings, or use the answer. Run the verification command for `debug` scope.
