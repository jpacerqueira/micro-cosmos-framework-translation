---
name: debrand-generic-integration-categories
description: Removed Slack/BambooHR references from generated reports and the Cartographer classifier — a full-repo audit found exactly 4 lines across 2 files, broadened the underlying detection to generic HR/ERP/CRM/comms-alerting categories rather than just relabeling text (2026-08-10)
metadata:
  type: project
---

Joao asked for every reference to Slack, BambooHR, and other internal organisation tool names to
be removed from generated output (reports, work-stream descriptions), replaced with generic
category language — his own suggested examples: "HR tool," "ERP flavour," "communications/alerts
tool."

## The audit (done before touching anything)

Searched every `.py`/`.js`/`.html`/`.md` file for Slack, BambooHR, and a broader list of common
third-party SaaS names (Workday, ADP, Gusto, Okta, Auth0, Twilio, SendGrid, Zendesk, Salesforce,
Confluence, Notion, HubSpot, Greenhouse, Lever, Namely) across `micro_cosmos/` and `scripts/` (the
report generators) — the full breadth of what "review all" and "broaden detection to all reports
specs source markup for orchestrations and pipeline runs" asked for. Result: exactly 4 lines
across 2 files —`micro_cosmos/tools/cartographer_tools.py` (the deterministic Cartographer path-rule
classifier) and `micro_cosmos/tools/seam_tools.py` (a generic default work-stream template). Every
other "slack" hit was the vendored `dagre.min.js` graph-layout library using the word in its
literal graph-theory sense (edge slack) — unrelated, not touched. No report-generator script
(`scripts/generate_*.js`) or template contains any of these names.

## Why this mattered beyond cosmetics

`seam_tools.py`'s `ws_04_ext_integrations` is one of the generic *default* work-stream templates
— shown to **every** customer regardless of their actual codebase, not conditional on the
customer actually having a Slack/BambooHR integration. So a customer with neither was seeing
"Isolate all third-party integrations (BambooHR, Slack, GraphQL, storage)..." verbatim in their
generated sprint-plan/synthesis report. This is the same "generic template bucket" mechanism
flagged before in `transferable-skills/memory/databricks-bundle-task-graph-seams.md` — a cosmetic gap there, a real
information-leak concern here.

Confirmed via `find` that no `examples/` estate has folders literally named `bamboohr`/
`slack-api` — so `cartographer_tools.py`'s Rule 4 path-detection matching those exact literal
strings was effectively dead code today, safe to fully replace (not just relabel) with zero risk
of regressing any existing example's classification behavior.

## The fix: broadened detection, not just relabeled text

Confirmed with Joao before implementing (a real architectural fork, not assumed): should the
underlying folder-name *detection* also be genericized, or just the visible text left pointed at
the same two literal vendor names? Chose to broaden detection too — Rule 4 now matches generic
third-party-integration folder-name categories (`/hris/`, `/hr-integration/`, `/payroll/`,
`/erp/`, `/crm/`, `/alerts-api/`, `/chatops/`, `/comms-api/`, plus the pre-existing
`/external-api/`) instead of the two vendor-specific literals. Deliberately kept non-overlapping
with the existing Rule 7 "Messaging" (`/notification`, `/pubsub`, `/activity-events`,
`/publisher` — internal event-bus architecture, a genuinely different concept from an external
SaaS comms/alerting client integration).

This is strictly better than a text-only fix: it removes the vendor coupling from the *code*, not
just its *description*, and makes the classifier detect the same category of real-world folder
across arbitrary customer codebases, not just ones that happen to use these two specific vendors'
literal directory-naming convention.

## Verification

New `tests/test_cartographer_classification.py` (12 tests — no prior coverage existed for this
classifier at all) confirms every new generic pattern classifies as `ExternalIntegrations`, and
confirms the old literal `/bamboohr/`/`/slack-api/` paths no longer specifically match Rule 4
(they fall through to the generic structural fallback, `Rule 14`, instead — confirming the
vendor coupling is genuinely removed, not just hidden behind new labels). All pass. Full suite:
48 passed (up from 36 earlier the same day), 1 skipped, the same 5 pre-existing unrelated
failures.

Live: ran a real estate (`examples/csharp-bankxyz_fraud_detection`) through Observer+Cartographer
in deterministic mode and confirmed neither `bounded_context_map.json` nor `work_streams.json`
contains "bamboohr"/"slack" anywhere. Closed the loop with a final repo-wide
`grep -ri "bamboohr|slack" micro_cosmos/` — zero matches outside the vendored `dagre.min.js`, confirming
the audit is actually complete rather than partially done.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/tools/cartographer_tools.py` | Rule 4 detection genericized; `ExternalIntegrations` description text genericized |
| `micro_cosmos/tools/seam_tools.py` | `ws_04_ext_integrations` work-stream template rationale genericized |
| `tests/test_cartographer_classification.py` | New automated regression test |
