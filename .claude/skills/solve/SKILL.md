---
name: solve
description: Tackles complex problems with a three-phase approach — fans out multiple Sonnet agents to explore approaches, the main Opus instance picks the best plan, then a fresh Opus agent executes with clean context. Use when facing hard bugs, architectural decisions, or problems where the best approach isn't obvious.
---

# /solve

Explore, judge, and execute — for problems worth thinking about from multiple angles.

## Phase 1 — Fan-out (Sonnet explorers)

1. **Frame the problem** — Write a clear problem statement (2-4 sentences): what needs to happen, what constraints exist, what's been tried.
2. **Define exploration angles** — Create 2-4 distinct approaches to explore. Each should be a genuinely different strategy, not minor variations.
3. **Launch explorers** — For each approach, use the Task tool:
   - `subagent_type: "Plan"`, `model: "sonnet"`
   - Pass: problem statement, the specific approach to explore, relevant file paths
   - Instruct: "Explore this approach to the problem. Return: (1) approach summary, (2) concrete implementation plan with file paths, (3) pros and cons, (4) key risks or unknowns, (5) estimated scope (files touched, complexity)."
   - Launch all Task tool calls in a single message so they run concurrently

## Phase 2 — Judge (main Opus instance)

No subagent — this happens in the main conversation to leverage accumulated project context.

1. **Compare proposals** — Read all explorer outputs side by side.
2. **Evaluate** — Score each approach on: correctness, simplicity, risk, alignment with existing architecture.
3. **Synthesize** — Pick the best approach. Incorporate useful insights from runners-up (e.g., an edge case one explorer identified that the chosen approach should handle).
4. **Prepare execution brief** — Write a concise implementation plan: problem statement, chosen approach, specific file changes, key decisions, and any caveats from the runners-up.

## Phase 3 — Execute (fresh Opus instance)

1. **Launch executor** — Use the Task tool:
   - `subagent_type: "general-purpose"`, `model: "opus"`
   - Pass ONLY: the execution brief from Phase 2. Do not pass explorer outputs — the executor gets clean context for maximum effectiveness.
   - Instruct: "Implement this plan. Read the relevant files, make the changes, and return: (1) files modified with summaries, (2) any deviations from the plan and why, (3) verification steps."
2. **Why a fresh instance** — The main context is now loaded with explorer outputs and comparison analysis. A fresh Opus instance has full context window available for the implementation, resulting in higher quality execution.

## Phase 4 — Verify (main instance)

1. **Review changes** — Read the modified files, confirm they match the chosen approach.
2. **Run verification** — Execute tests, linting, type checks as appropriate.
3. **Handle issues** — If the executor missed something, fix it directly or re-run Phase 3 with additional instructions.

## When to Use This

- Debugging a complex issue with multiple possible root causes
- Choosing between architectural approaches (e.g., restructuring a module)
- Implementing a feature where the design isn't obvious
- Refactoring with multiple valid end-state designs

## When NOT to Use This

- Simple tasks with obvious implementations — use direct editing
- Single-approach problems — use `/fork` or work directly
