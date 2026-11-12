# CALM CLI

Installs the FINOS `calm-cli` and bundles a Claude Code skill for working with [FINOS CALM](https://calm.finos.org) (Common Architecture Language Model) architectures.

## What's in this folder

| File | Purpose |
|---|---|
| [`cli-install.sh`](cli-install.sh) | Installs `calm-cli` via Homebrew |
| [`.claude/skills/calm/`](.claude/skills/calm/) | The CALM Claude Code skill, scoped to this directory — `SKILL.md` plus 14 `calm-prompts/*.md` instruction files covering every CALM building block |

## Install

```bash
./cli-install.sh
# or directly:
brew install calm-cli
```

Verify:

```bash
calm --version
```

## The CALM Claude Code skill

The skill turns Claude into a specialized assistant for creating and validating CALM architecture models — JSON documents that describe systems, how they connect, who governs them, and how they evolve over time. Invoke it as `/calm`; on first use in a session it reads all 14 `calm-prompts/*.md` files as its reference manual.

### Building blocks

- **Core structure** — every CALM model is a `.architecture.json` file with `$schema`, `unique-id`, `name`, and `description`. Everything else is optional but typically includes `nodes`, `relationships`, `flows`, and `controls`.
- **Nodes** — the "boxes" in the diagram. Each needs `unique-id`, `node-type` (`actor`, `service`, `database`, `webclient`, `system`, etc.), `name`, and `description`. Nodes can carry `interfaces`, `controls`, and `metadata`.
- **Relationships** — the edges. Exactly one of four types per relationship:
  - `connects` — point-to-point service connections (source node → destination node)
  - `interacts` — an actor using one or more systems (human/external system → app)
  - `deployed-in` — infrastructure containment (nodes inside a cluster/container)
  - `composed-of` — logical composition (system made of sub-services)
- **Interfaces** — how a node exposes itself. Two modes: `interface-definition` (strict, references an external schema) or `interface-type` (flexible, any extra properties allowed). Never mix properties from both.
- **Flows** — business processes that traverse *existing* relationships. A flow is a sequenced list of `transitions`, each referencing a relationship's `unique-id` with a direction and description. Flows narrate; they don't create new connections.
- **Controls** — compliance and governance rules attached to architectures, nodes, or flows. Each control has a `description` and a `requirements` array, where each requirement points to an external requirement schema (`requirement-url`) plus either an inline `config` or an external `config-url`.
- **Standards** — JSON Schema 2020-12 documents that extend CALM components with org- or domain-specific fields (cost centre codes, environment tags, NIST control structure). Controls typically reference requirement files validated against a Standard, giving consistent structure across a framework (e.g. every NIST or ISO 27001 control in a repo).
- **Metadata** — free-form supplementary info (version, owner, SLA, etc.) on any element. Either a single flat object or an array of objects.
- **Patterns** — reusable architecture templates expressed as JSON Schema. `calm generate` instantiates a pattern into a concrete architecture. Patterns use `const` to lock structural identifiers, and `anyOf`/`oneOf` to offer choices (e.g. "PostgreSQL or MySQL?"). Rule of thumb: `const` for IDs and types, `type: string` for descriptions so users fill them in.
- **Decorators** — standalone `.decorator.json` files that attach supplementary context to architecture elements without touching the architecture file itself (deployment status, threat model data, ADRs, runbook links, business ownership). Each decorator targets one or more architecture files (`target`) and specific element IDs within them (`applies-to`); `data` is free-form. Useful when a different team owns the deployment/security context than the team that owns the architecture.
- **Moments & Timelines** — for modelling how an architecture evolves. A **moment** is a snapshot at a point in time (a node with `node-type: "moment"`, requiring `details.detailed-architecture`, optionally `valid-from` and ADR links; moments cannot have `interfaces`). A **timeline** (`*.timeline.json`) is an ordered collection of moments.

### CLI commands

| Command | What it does |
|---|---|
| `calm validate -a <file>` | Validate an architecture |
| `calm validate -p <file>` | Validate a pattern |
| `calm validate -p <pattern> -a <arch>` | Full validation — architecture against pattern |
| `calm generate -p <pattern>` | Scaffold an architecture from a pattern |
| `calm docify -a <file> -o ./docs` | Generate a documentation website |
| `calm template -a <file> -o <out>` | Generate files via Handlebars templates |
| `calm init-ai -p claude` | Bootstrap Claude Code CALM prompts in a repo |

Use `--url-to-local-file-mapping` for offline/CI builds where pattern references point to URLs that aren't published yet — it maps those URLs to local files.

Validation produces two result types: `jsonSchemaValidationOutputs` (schema compliance) and `spectralSchemaValidationOutputs` (lint rules). Both must show `"hasErrors": false` before committing — subtle rules like `additionalProperties: false` on interfaces, or the `oneOf` constraint on relationship types, fail validation silently if missed.

### Workflow

1. Design nodes and relationships.
2. Add interfaces to nodes where needed.
3. Optionally layer on flows (business processes), controls (governance), and metadata.
4. Validate with `calm validate -a <file>`.
5. If using patterns: `calm generate -p <pattern>` → fill in blanks → validate against the pattern.
6. Add decorators for cross-cutting concerns owned by other teams.
7. For evolution over time: capture moments in a timeline file.

See [`calm/examples/java-bankxyz_fraud_detection/`](../examples/java-bankxyz_fraud_detection/) for a worked example, including how to load a generated architecture into [CALM Studio](https://calm.finos.org/working-with-calm/calm-studio/).
