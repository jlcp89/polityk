# Vertical Slicing — Deep Reference

Sibling aux to `SKILL.md`. Read this when drafting issues in Step 3.

## Why vertical, not horizontal

Layer-by-layer construction (build the whole schema → build the whole CA → build the whole endpoint → build the agent) ships nothing demoable until the last layer lands. Feature-by-feature construction (each issue picks one capability and follows it through every layer it crosses, stubbing layers that other issues will replace later) keeps every commit demoable.

Each AFK iteration is supposed to ship one end-to-end working capability. A horizontal issue cannot do that — it leaves the system half-built, with no test that exercises the full path. A vertical issue always can, because it owns every layer the test needs.

## Anti-patterns (do NOT do this)

These are real titles that look reasonable but are horizontal:

- `Org/Tenant/User schema + identity resolver + cross-tenant rejection tests` — schema-and-tests-only. Nothing consumes the resolver in this issue. The agent gets nothing it can run end-to-end.
- `internal/tenantca with KMS interface + KMS fake + chain` — CA layer only. No endpoint, no client, no proof the chain even works in a real flow.
- `Bootstrap-token enrollment endpoint with atomic consume+sign + expiry + tenant binding` — endpoint plumbing without a client that exercises it. Pure infrastructure with no end-to-end demo.
- `mTLS heartbeat: dispatch long-poll + /v1/agent/dispatch + transport loop + health envelope` — four concerns across three modules. Each one is an issue on its own.

The diagnostic: if the title uses `+`, `and`, `with`, or a comma to chain concerns, the issue is doing too much OR is building one layer all at once.

## Vertical replacements (good)

For the same feature surface, vertical issues look like:

- `Tenant create + agent enroll with stub CA → agent receives mTLS cert` — one capability across schema + endpoint + agent client + e2e test, with the CA stubbed. The next issue swaps the stub.
- `Replace stub CA with real KMS-backed CA in the existing enroll path` — the enroll path already exists from the prior issue; this issue is the swap-in. Title still names one capability.
- `Add rate-limit branch to existing enroll path + agent receives 429 + retries` — extends the working path with one new branch; doesn't build a new layer.

Each one is demoable: the prior issue's end-to-end test still passes, the new issue adds a new end-to-end test for the new behavior.

## Hard caps as backstop

- ≤1 user story per issue (often a sub-part of one)
- ≤2 modules emphasized in the title (one is better)
- ≤1 verb-phrase in the title (e.g., "agent enroll with stub CA" — "enroll" is the verb)

If an issue exceeds these, split it.

## Verticality self-check (required before showing the user)

For each proposed issue, before presenting it:

1. Name the layers it touches (schema, endpoint, agent, tests, etc.).
2. If it touches only one layer → restructure as a vertical extension of an earlier issue or merge it into an issue that will consume it.
3. Does the title contain `+`, `and`, `with`, or `,`? → split or restructure until the answer is no.
4. Count user stories and modules; if over the caps, split.

Issues that pass all four checks are ready to show the user.

## Dependency ordering (required for AFK execution)

Vertical issues that are independently demoable are not always independently executable. Two issues are serialization-dependent when they write to shared infrastructure:

- **Migration files**: two workers cannot both create `migrations/0009_x.sql` and `migrations/0009_y.sql` — only one number can exist. Every issue that introduces a migration must block all subsequent migration issues in the set.
- **Generated code / interfaces**: if issue A generates a file that issue B imports, B is blocked by A.

**Check**: after the verticality self-check, scan all issues for shared paths. Add `Blocked by` relationships to serialize them. `## Blocked by` is never blank — write `- None — can start immediately` if truly unblocked.

This section is load-bearing: the AFK parallel supervisor reads `## Blocked by` to decide concurrency. An empty field means "no dependencies" and will cause concurrent execution of dependent issues.
