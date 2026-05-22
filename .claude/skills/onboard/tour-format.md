# Onboard — Quickstart, Data-Flow, and Common-Tasks Templates

Used by `/onboard` Steps 3, 4, and 5.

## Quickstart Template (Step 3)

```
## Quickstart — {project name}

### Mission
{mission from CONTEXT.md — or project description from CLAUDE.md if no CONTEXT.md}

### Key architecture decisions
- {ADR summaries from CONTEXT.md — or inferred from code if no CONTEXT.md}
- {decision 1 — e.g., "Monorepo with NX, shared libs in libs/"}
- {decision 2 — e.g., "JWT auth at gateway, services trust forwarded headers"}
- {decision 3}

### Active work
- {current branch from `git branch --show-current`}
- {recent activity from `git log --oneline -10`}
- {open work from issue tracker — `gh issue list` or `ISSUES.md`}

### Gotchas
- {gotcha 1 from CLAUDE.md}
- {gotcha 2}

### Conventions
- {convention 1 — e.g., "kebab-case for files, PascalCase for components"}
- {convention 2}

### Essential commands
- Dev:   `{dev command}`
- Test:  `{test command}`
- Lint:  `{lint command}`
- Build: `{build command}`
```

## Primary Data-Flow Trace (Step 4)

Walk through the main flow from entry to response:

1. **Entry point** — where requests arrive (e.g., `src/main.ts`, `cmd/server/main.go`)
2. **Routing** — how requests get routed (e.g., Express router, chi mux)
3. **Business logic** — where domain logic lives (e.g., `services/`, `internal/`)
4. **Data persistence** — how data is stored (repository pattern, ORM)
5. **Response** — how responses are formatted and sent

If the user specified a focus area, trace the flow for that specific area.

> "Here's how a typical request flows through the system:"
> {trace with file paths and key function names}

## Common Tasks Template (Step 5)

```
## Common Tasks

### Add a new endpoint/route
1. {step with file path}
2. {step}

### Add a new model/migration
1. {step}
2. {step}

### Write tests for a feature
1. {step with test file location}
2. {step with test patterns}

### Debug a failing test
1. {step}
2. {step}
```

Tailor each block to the project's actual patterns from `CLAUDE.md` and the code structure.

## Mental-Model Save (Step 6)

If the user approves saving, write `~/.claude/projects/<project>/memory/architecture.md` with:

- Project type and stack
- Key architecture patterns
- Primary data flow
- Important file paths
- Active conventions
