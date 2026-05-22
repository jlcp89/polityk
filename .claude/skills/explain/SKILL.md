---
name: explain
description: Deep-dive code explanation with Mermaid diagram generation. Provides layered explanations from purpose to implementation details and generates appropriate diagrams for stakeholder presentations. Use when understanding unfamiliar code, documenting architecture, or preparing technical presentations.
---

# Explain — Deep Dive with Diagrams

Deep-dive explanation with Mermaid diagram generation for documentation and stakeholder presentations.

## Workflow

### Step 1: Identify Target

If `$ARGUMENTS` (the text passed after the slash command, e.g., `/explain src/auth/`) specifies the target, use it. Otherwise ask:

> "What should I explain? (module, file, function, pattern, or architecture)"

Target types:
- **Module** — a directory or package (e.g., `src/billing/`)
- **File** — a single file (e.g., `src/auth/middleware.ts`)
- **Function** — a specific function or method
- **Pattern** — a design pattern used in the project (e.g., "error handling")
- **Architecture** — the overall system structure

### Step 2: Read & Trace

1. Read the target file(s)
2. Read direct dependencies (imports, calls)
3. Read related tests (if they exist)
4. Trace the execution path from entry to exit

### Step 3: Explain (Layered)

Present the explanation in layers of increasing detail:

**Layer 1 — Purpose** (1-2 sentences):
> "{What this does and why it exists}"

**Layer 2 — How it works** (paragraph):
> "{High-level description of the mechanism — inputs, processing, outputs}"

**Layer 3 — Key decisions** (bullet list):
- **{Decision}** — {why it was built this way}
- **{Decision}** — {trade-off made}
- **{Decision}** — {alternative considered}

**Layer 4 — Details** (code walkthrough):
Walk through the critical sections of code, explaining:
- Control flow and branching logic
- Error handling strategy
- Integration points with other modules
- Performance-sensitive sections

### Step 4: Generate Mermaid Diagram

Select the diagram type based on the subject:

| Subject | Diagram Type | Mermaid Syntax |
|---------|-------------|----------------|
| Architecture / modules | Component diagram | `graph TD` |
| Data flow / request lifecycle | Sequence diagram | `sequenceDiagram` |
| State machine | State diagram | `stateDiagram-v2` |
| Class hierarchy | Class diagram | `classDiagram` |
| Process / workflow | Flowchart | `flowchart LR` |

Generate as a fenced code block (renderable in GitHub, Notion, etc.):

````
```mermaid
{diagram content}
```
````

Guidelines for diagram quality:
- Keep nodes to 10-15 maximum for readability
- Use descriptive labels, not abbreviated codes
- Show the most important relationships, not every connection
- Include a title comment at the top: `%% {diagram description}`
- Group related nodes with subgraphs where appropriate

### Step 5: Offer Follow-up

> "Want me to:"
> 1. Explain related code
> 2. Generate a different diagram type
> 3. Go deeper into a specific section
> 4. Save this explanation to documentation
