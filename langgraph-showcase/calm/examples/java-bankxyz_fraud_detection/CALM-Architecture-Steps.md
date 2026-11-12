# CALM Architecture — Generation & Validation Steps

How `java-bankxyz-fraud-detection.architecture.json` in this folder was produced, so the same process can be repeated for another example application.

## 0. Prerequisites

- FINOS `calm-cli` installed and on `PATH`:
  ```bash
  which calm
  calm --version
  ```
  (Installed here via Homebrew: `brew install calm-cli`, v1.47.1.)
- The CALM skill prompts loaded for schema guidance: `calm/calm-prompts/*.md` (architecture, node, relationship, interface, metadata, control, flow creation guides, plus `calm-cli-instructions.md`).

## 1. Understand the source application

Before writing any CALM JSON, read the target codebase to extract real components, connections, and business rules — do not invent structure. For `examples/java-bankxyz_fraud_detection/` the following were read in full:

| File | What it gave the model |
|---|---|
| `ARCHITECTURE.md` | Bounded contexts (TransactionEntry, FraudScoring, AlertManagement), call chains, data flow diagram, business invariants, Oracle schema, messaging config |
| `README.md` | API summary, decision thresholds, quick-start / deployment shape |
| `docker-compose.yml` | The 3 deployable containers (`oracle`, `activemq`, `app`), their hostnames/ports, and the shared bridge network — this became the `deployed-in` relationship and the `network` node |
| `fraud_api/openapi.yaml` | Exact REST endpoints (`/api/v1/authorise`, `/api/v1/batch/run`), request/response shapes, and the COBOL/CICS/Db2/IBM MQ legacy-origin note used in architecture-level metadata |
| `src/.../config/JmsConfig.java` | Confirmed ActiveMQ is a drop-in for the production IBM MQ queue, and that the queue name is stable for case-management compatibility |
| `Dockerfile` | Confirmed the app is a single Spring Boot JAR exposing port 8080 |

## 2. Map source concepts to CALM building blocks

| Source concept | CALM element | Notes |
|---|---|---|
| Card/ATM/Online/Branch channels | `actor` node | External initiator, not implemented in this codebase |
| Case management system (consumer of `FRAUD.ALERT.QUEUE`) | `actor` node | External consumer, out of scope of this repo |
| The Spring Boot app as a whole | `system` node | Parent, `composed-of` its 3 bounded contexts |
| `RealtimeCheckController`, `TransactionMonitorService`, `FraudBatchJobConfig` | `service` node (`transaction-entry-service`) | One bounded context per `ARCHITECTURE.md` §2 |
| `FraudRulesService`, `VelocityCheckService`, `CustomerProfileService`, `WatchlistService` | `service` node (`fraud-scoring-service`) | Same |
| `AlertWriterService`, `MqNotificationService` | `service` node (`alert-management-service`) | Same |
| Oracle XE container + 9 JPA tables | `database` node | Interface = JDBC host/port/service-name from `docker-compose.yml` |
| ActiveMQ container + `FRAUD.ALERT.QUEUE` | custom node-type `"message-broker"` (CALM node-type enum allows any string) | Interfaces = broker port, web console URL, queue name |
| `fraud-net` Docker bridge network | `network` node | Target of a `deployed-in` relationship |
| REST/method calls between the above | `connects` relationships | `protocol: "JDBC"` used where it fits the CALM protocol enum; omitted (and noted in `metadata.actual-protocol`) where the real protocol (JMS/OpenWire) isn't in the enum |
| Channel → API call | `interacts` relationship | Actor-to-system, per `relationship-creation.md` |
| Real-time call chain (`ARCHITECTURE.md` §3) | `realtime-authorisation-flow` | `transitions` reuse the `connects`/`interacts` relationships above, in call order |
| Nightly batch job (`@Scheduled(cron=...)`) | `nightly-batch-flow` | Reuses the same relationships in batch order — flows narrate, they don't create new connections |
| Business invariants #1, #3, #7 (`ARCHITECTURE.md` §8) | `controls` (`watchlist-screening`, `realtime-sla`, `monetary-precision`) | Architecture-level, inline `config`, placeholder `requirement-url` |

## 3. Write the architecture file

Single self-contained file, following `architecture-creation.md`:

- Path: `calm/examples/<app-name>/<app-name>.architecture.json`
- Required top-level fields: `$schema` (`https://calm.finos.org/release/1.2/meta/calm.json`), `unique-id`, `name`, `description`
- Populated `metadata`, `nodes`, `relationships`, `flows`, `controls`
- Every `node` has `unique-id`, `node-type`, `name`, `description` (required by `node-creation.md`)
- Every `relationship` has exactly one `relationship-type` key (`interacts` / `connects` / `composed-of` / `deployed-in`), per the schema's `oneOf` constraint
- Every `flow` has `unique-id`, `name`, `description`, and at least one `transitions` entry referencing an existing `relationship-unique-id`
- Every `control` has a `description` and a `requirements` array, each requirement having `requirement-url` plus exactly one of `config` / `config-url`

## 4. Validate

Mandatory before treating the file as done — JSON validity is not the same as CALM validity:

```bash
calm validate -a calm/examples/java-bankxyz_fraud_detection/java-bankxyz-fraud-detection.architecture.json --strict -f pretty
```

Expected output:

```
Summary
- Errors: no (0)
- Warnings: no (0)
- Info/Hints: 0

No issues found.
```

To confirm machine-readably (used in CI or scripting):

```bash
calm validate -a <file> --strict -o result.json
python3 -c "import json; d=json.load(open('result.json')); print(d['hasErrors'], d['hasWarnings'])"
# Expect: False False
```

If errors appear, they land in `jsonSchemaValidationOutputs` (schema violations) or `spectralSchemaValidationOutputs` (lint rules) in the JSON output — fix all of them, do not proceed with warnings/errors present.

## 5. Load the architecture into CALM Studio (visual view/edit)

CLI validation confirms the file is *schema-correct*; opening it in [CALM Studio](https://calm.finos.org/working-with-calm/calm-studio/) confirms it's also *visually sane* (nodes/relationships render as an intelligible diagram, nothing overlapping or orphaned).

### 5.1 Start Studio

CALM Studio lives in the `finos/architecture-as-code` monorepo (`main` branch, workspace `@calmstudio/studio`) — see `calm/calm-studio-server/` in this repo for the install tooling. From the repo root:

```bash
cd calm/calm-studio-server
make install   # first time only — clone/pull architecture-as-code, npm install, build calm-models + calm-core
make start     # starts the dev server; skips install if already installed
```

`make start` polls until it's reachable and prints `CALM Studio is up at http://localhost:5173`. `make stop` shuts it down (kills whatever holds port 5173). `GIT_HOME` (default `~/Documents/GitHub`) controls where `architecture-as-code` is cloned — override with `GIT_HOME=/some/path make start`.

### 5.2 Open the architecture file

Studio always starts with a **blank canvas** — there is no URL parameter or CLI flag to preload a file, and it does not scan any folder on startup. You load a file manually, every session:

1. Open `http://localhost:5173` in a browser (Chrome/Edge get the full native file picker via the File System Access API; Firefox/Safari fall back to a plain file-input dialog with the same result).
2. Click the **Open** button in the toolbar, or press **Cmd+O** / **Ctrl+O**.
3. Browse to and select `calm/examples/java-bankxyz_fraud_detection/java-bankxyz-fraud-detection.architecture.json`.
4. Studio renders the 9 nodes and 10 relationships on the canvas; use the properties panel to inspect flows and controls per node.

(The distinct **New** button/`⌥N` shortcut discards the canvas and starts empty — don't confuse it with **Open**.)

## 6. Result for this application

- File: `calm/examples/java-bankxyz_fraud_detection/java-bankxyz-fraud-detection.architecture.json`
- 9 nodes, 10 relationships, 2 flows, 3 controls
- `calm validate --strict`: exit code 0, `hasErrors: false`, `hasWarnings: false`
- Confirmed opening cleanly in CALM Studio (`make start` in `calm/calm-studio-server/`, then Open in the browser UI)

## Repeating this for a different example application

1. Read that app's architecture docs, compose/deployment files, and API contracts (step 1).
2. Re-do the mapping table in step 2 for its actual bounded contexts, datastores, and messaging.
3. Write `calm/examples/<app-name>/<app-name>.architecture.json` following the same schema rules (step 3).
4. Run the same `calm validate -a ... --strict` command (step 4) and fix until clean.
5. Optionally open it in CALM Studio (step 5) to sanity-check the diagram visually.
