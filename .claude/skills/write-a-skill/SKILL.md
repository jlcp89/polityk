---
name: write-a-skill
description: Author a new skill in the minimal c2 style. Use when creating, splitting, or rewriting a SKILL.md.
---

# write-a-skill

A skill teaches the agent ONE thing about ONE codebase. If you cannot state that thing in one sentence, the skill is too broad.

## Style rules

- **Body ≤ 50 lines.** Hard cap 120 (validator warns). If you need more, split — see "When to split".
- **Frontmatter is `name` + `description` only.** Nothing else unless mechanically required (e.g. `disable-model-invocation` for `recover`).
- **Description must contain "Use when".** First sentence: what it does. Second sentence: when to fire.
- **One nesting level.** No "Phase 1 → Step 1.1 → sub-bullet". Pick H2 sections; avoid H3.
- **Imperative bullets > prose.** "Run the typecheck." Not "It is recommended that you consider running the typecheck."
- **No "MANDATORY"/"FORBIDDEN" sub-sections** that restate a global rule. If a guard truly belongs to *this* skill, write it as one in-place line.
- **Cross-references only when mechanical** (e.g. a checklist file the skill walks). No "see also" tail listing every related skill.
- **No examples** unless they disambiguate something a careful reader would still get wrong.

## Description format

`{capability, third-person}. Use when {concrete trigger — keywords, file types, or context}.`

Good: "Reviews code changes for quality and security. Use when finishing a feature or before opening a PR."
Bad: "Helps with code review." (no trigger, no specificity)

## When to split into sibling files

Split only when the body would otherwise exceed 120 lines. Place aux files next to `SKILL.md`:

```
my-skill/
  SKILL.md          # the entry point, ≤ 50 lines
  checklist.md      # walked mechanically by the skill
  examples.md       # only if examples earned their place
```

Reference an aux file with a relative link: `[checklist](checklist.md)`. The validator checks these resolve.

## Before committing

Run `bash validate.sh` from the c2 root. The minimal-style check enforces frontmatter keys, "Use when", and the body cap.
