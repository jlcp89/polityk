# Context Assembly Guide — Feature Scoping

> Great specs come from great context. Automate the obvious, ask about the unknowable.

This framework feeds into **spec generation**. Context assembly gathers what's needed to write a precise SPEC.md, combining automated codebase analysis with targeted questions.

## Layer 1 — Codebase Research (automated)

Before asking the user anything, use an Explore agent to gather:

| Signal | What to Look For | Maps to Spec Section |
|--------|-------------------|---------------------|
| Similar features | Where do comparable features live? What patterns do they follow? | Changes (file selection) |
| Existing APIs | What interfaces, types, and contracts already exist? | Changes (constraints) |
| Test patterns | How are similar features tested? What test utilities exist? | Test Plan |
| Architecture | What's the module boundary? Where does this feature fit? | Changes (ordering) |

Produces a **Feature Context** with what's known and what's still uncertain.

## Layer 2 — Complexity Classification (automatic)

| Level | Criteria | Question Budget |
|-------|----------|-----------------|
| **trivial** | 1-3 files, follows existing pattern exactly | 1 question (just gotchas) |
| **standard** | 4-10 files, some new patterns needed | 2-3 questions |
| **complex** | 10+ files, new patterns, cross-cutting concerns | 3-4 questions |

## Layer 3 — Targeted Questions

Present the Feature Context first, then ask only what can't be inferred. Pick from this pool based on complexity:

**Always ask (all levels):**

> **Gotchas**: What edge cases, error scenarios, or constraints should we handle? What "obvious" approach doesn't work here?

**Ask for standard+ complexity:**

> **Acceptance**: How will we know this feature is complete? What are the acceptance criteria?

> **Constraints**: Are there technical constraints, design decisions, or patterns we must follow?

**Ask for complex features:**

> **Risks**: What parts are most uncertain or risky? What assumptions might be wrong?

## Context → Spec Mapping

| Context Source | Spec Section |
|---------------|-------------|
| Feature description | Problem |
| Layer 1 research + constraints answer | Solution, Changes |
| Acceptance answer | Verification |
| Gotchas answer | Test Plan (edge cases) |
| Layer 1 architecture analysis | Changes (ordering) |

## Example: User Profile Edit Feature

### Feature Context (Layer 1 automated)
- Similar features: `src/api/orders.controller.ts` follows PATCH pattern with Zod validation
- Existing types: `User` model in `src/models/user.ts`, has `displayName` separate from `firstName`/`lastName`
- Test pattern: controller tests in `__tests__/` use `supertest` + factory helpers
- Architecture: controller → service → repository pattern

### Complexity: standard (5-7 files, follows existing patterns mostly)

### Targeted Questions (2 questions)
1. **Gotchas**: Avatar uploads go to S3 via presigned URLs, not through our API. Email changes require re-verification. Don't forget to invalidate the user cache after updates.
2. **Acceptance**: Changes persist and show immediately. Avatar preview before upload.

### Resulting SPEC.md

```markdown
# Feature Spec: User Profile Edit

## Problem
Users cannot edit their profile information (name, email, avatar).

## Solution
Add PATCH endpoint with validation + React form with optimistic updates + S3 presigned URL upload.

## Changes

### File: src/api/users.controller.ts
- Add PATCH /users/:id endpoint with Zod validation
- Email change triggers re-verification flow

### File: src/components/ProfileForm.tsx
- New form component with optimistic updates
- Avatar upload via presigned URL (not through API)

### New File: src/lib/s3-presigned.ts
- Presigned URL generation for avatar uploads

## Test Plan
- [ ] Unit tests for PATCH validation (invalid email, missing fields)
- [ ] Integration test for profile update → cache invalidation
- [ ] Edge cases: email re-verification, avatar upload failure, displayName vs firstName
```
