---
name: debugging
description: Agentic systematic debugging cycle with instrumentation and evidence-based fixing. Use when a bug is reported, unexpected behavior is observed, or a test is failing and the root cause isn't obvious.
---

# Agentic Debugging Workflow

Follow this 5-step process to resolve errors through evidence-based analysis rather than guessing.

## 1. Hypothesis Generation

Analyze the codebase and generate at least three potential root causes. Present these hypotheses to the user before modifying any code.

## 2. Code Instrumentation

Insert temporary, detailed logs at critical execution points.

- **Requirement:** Use a unique prefix — e.g. `console.log("[DEBUG-AGENT] <variable>:", value);` or `print("[DEBUG-AGENT]", value)` — so cleanup is one grep.
- Focus on data transformations, conditional branches, and state changes.

## 3. Evidence Collection

Run a reproduction script via `bash` if available, or ask the user to trigger the bug.

- Filter output for the `[DEBUG-AGENT]` prefix.
- Compare actual runtime data against your initial hypotheses.
- Identify which hypothesis the evidence supports or rules out.

## 4. Evidence-Based Fix

Identify the exact root cause from the logs. Implement the minimal fix and explain why the other hypotheses were ruled out.

## 5. Automated Cleanup

Once the fix is confirmed:

- **Mandatory:** Remove all `[DEBUG-AGENT]` instrumentation logs added in Step 2.
- Run existing test suites to verify no regressions were introduced.
