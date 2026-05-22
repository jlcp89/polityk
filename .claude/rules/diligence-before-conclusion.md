---
paths: [".claude/skills/**", ".claude/agents/**"]
---

# Diligence Before Conclusion

Surface diagnostic evidence (a `diff`, a placeholder token, a stack trace, a single grep hit) is **not** semantic ground truth. Before you draw a conclusion, escalate, or present options to the user, you must prove you understand *why* the surface looks the way it does.

## Principle

**Syntactic ≠ semantic.** Two files differing in `{{PLACEHOLDER}}` tokens, a `diff` showing many removed lines, a single error string in a log — none of these tell you the *meaning* of the change. The meaning lives in `git log`, in the recent commit messages, in `git diff -p` against the changed files. Read those first.

## Red-Flag Phrases

If you catch yourself about to write any of the following without having run `git log` on the relevant area, **stop**:

- "looks wrong", "this is incompatible", "wrong direction"
- "I see N options" (followed by an escalation)
- "the diff shows X is broken"
- "we should cancel and redirect"
- "let me ask the user how to proceed" (when you haven't yet read what changed)

These phrases are diagnostic-evidence-as-conclusion. Replace them with diligence.

## Required Pre-Conclusion Actions

Before any conclusion / escalation / options-list inside an inference-driven skill workflow:

1. Run `git log --oneline -20` on the relevant repo (or `git -C <root> log --oneline -20` for a related repo).
2. Run `git log -p -5 -- <changed-area>` on the files you observed.
3. State the **semantic** change in **one sentence** in the conversation. Not the file count. Not the placeholder delta. The *meaning* of what was changed and why.

Only after step 3 may you propose options, escalate, or stop.

## Forbidden Without the Pre-Conclusion Summary

- Cancelling a skill mid-flight ("this is wrong, stopping")
- Presenting the user with a multi-option redirect ("(a) X, (b) Y, (c) Z — which?")
- Drawing a conclusion from a `diff -u` of templates vs installed files
- Treating placeholder-token divergence as a compatibility verdict
- "Re-run /<skill> if you want option (b)"-style hand-offs

## Why This Rule Exists

A past `/update` run on the c2 source repo treated `{{PLACEHOLDER}}` divergence between templates and installed files as proof of "wrong direction — c2-on-c2 incompatible," and escalated. The actual semantic change was a routine v0.4.3 HANDOFF→CONTEXT migration; reading three lines of `git log` would have shown that. The user spent three turns redirecting back. This rule encodes the diligence step that prevents that failure.

## How to Apply

This rule auto-fires inside any `.claude/skills/**` or `.claude/agents/**` workflow. Inference-driven skills (`/update`, `/setup`, `/wrap`, `/refactor`, `/new-feature`) have a Phase −1 / Step 0 that requires the pre-conclusion summary in the transcript. If you are inside one of those skills and have not yet stated the semantic change, **the conclusion you are about to write is forbidden**.
