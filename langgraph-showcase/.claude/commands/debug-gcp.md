# Debug Micro-Cosmos Cloud Run deployments

Diagnose a live `micro-cosmos-web` or `micro-cosmos-llmgateway` Cloud Run service by
pulling ground truth directly from GCP (`gcloud`/`gcloud logging read`)
rather than reasoning from pasted log excerpts alone — pasted excerpts are
often incomplete or conflate unrelated request streams (confirmed the hard
way on 2026-07-14: a bug initially misread as an HTTP/HTTPS scheme issue,
then as a cold-start timing race, was actually a VPC-egress/ingress
networking bug — only found by querying `run.googleapis.com/requests`
directly and seeing it was completely empty).

$ARGUMENTS = optional: `web` (micro-cosmos-web only), `llmgateway`
(micro-cosmos-llmgateway only), `connectivity` (cross-service — is micro-cosmos-web
actually able to reach micro-cosmos-llmgateway at all). Default to asking which
scope if not specified.

## Before running anything

1. Confirm project/region are resolvable:
   ```bash
   gcloud config get-value project
   gcloud auth list --format="value(account)"
   ```
   If the project isn't already set to the right one, `gcloud config set
   project $PROJECT_ID` first (or pass `--project=` explicitly on every
   command below). Default region is `europe-west4` unless the user says
   otherwise.
2. Read `transferable-skills/memory/gcp-deployment.md` and
   `.claude/commands/deploy-gcp.md` first — both contain a large, growing
   catalog of already-diagnosed failure patterns (39+ items as of
   2026-07-14: kv_cache_dtype crashes, port mismatches, auth 401s, GCS
   FUSE stalls, `lms load` hangs, VPC-egress/ingress gaps, org-policy
   ingress restrictions, and more). Check the symptom against that catalog
   before assuming it's new — most Cloud Run failures in this project have
   already been root-caused once.
3. **Do NOT suggest `gcloud run services proxy` to bypass
   `--ingress=internal`** — it attaches an IAM identity token to a request
   against the same public endpoint, it does not tunnel through the VPC.
   It fails identically to a plain request against an internal-only
   service and will produce a misleading "still broken" result. See
   checklist item 12 in `deploy-gcp.md`.

## Steps by scope

### `web` — debug micro-cosmos-web

```bash
# Full service state: ingress, traffic split, VPC egress config, instance limits
gcloud run services describe micro-cosmos-web --region=europe-west4 \
  --format="yaml(status.traffic,status.conditions,spec.template.metadata.annotations,metadata.annotations)"

# Revision history
gcloud run revisions list --service=micro-cosmos-web --region=europe-west4 \
  --format="table(metadata.name,metadata.creationTimestamp,status.conditions[0].status)"

# Raw container logs (app-level: login, session, pipeline errors)
gcloud run services logs read micro-cosmos-web --region=europe-west4 --limit=100

# Cloud Run's own per-request log (GFE-level — shows every request that
# actually reached the service, including ones the container never saw)
gcloud logging read 'logName="projects/'"$(gcloud config get-value project)"'/logs/run.googleapis.com%2Frequests" AND resource.labels.service_name="micro-cosmos-web"' \
  --format="table(timestamp,httpRequest.status,httpRequest.requestUrl,httpRequest.remoteIp)" \
  --limit=50 --order=desc --freshness=2h
```

Check for: repeated early-run 404s on `/runs/{id}/seams` or
`/runs/{id}/artifacts/*` — this is expected/benign (dashboard polling for
artifacts before the producing phase has run; see `app.py`'s
`seam_findings()`), not a bug on its own. Login-loop or session errors →
check `SESSION_SECRET_KEY`/`SESSION_HTTPS_ONLY` per deploy-gcp.md item 15.

### `llmgateway` — debug micro-cosmos-llmgateway (GPU service, vLLM or LM Studio engine)

```bash
# Full service state: ingress, GPU/instance config, traffic
gcloud run services describe micro-cosmos-llmgateway --region=europe-west4 \
  --format="yaml(status.traffic,status.conditions,spec.template.metadata.annotations,metadata.annotations)"

# Revision history — when did the current revision actually start?
gcloud run revisions list --service=micro-cosmos-llmgateway --region=europe-west4 \
  --format="table(metadata.name,metadata.creationTimestamp,status.conditions[0].status)"

# Raw container logs — model load progress, watchdog messages, crash tracebacks
gcloud run services logs read micro-cosmos-llmgateway --region=europe-west4 --limit=200
```

Read the log chronologically and classify what's happening before guessing:
- Mount → GCS FUSE messages → `vllm serve`/`lms load` starting → weight
  loading progress → compile/warmup/CUDA-graph-capture → ready. A slow but
  *progressing* sequence is a cold start, not a bug (a ~62GB model can
  legitimately take 10+ minutes end-to-end).
- A traceback or `exit(1)`/`Container called exit(1)` partway through is a
  genuine crash — check the exact error against deploy-gcp.md's checklist
  (items 8-11, 19-21, 26, 38 cover specific confirmed crash signatures:
  `kv_cache_dtype`, `exitCode=127`/missing runtime, 401 `invalid_api_key`,
  wrong CLI flags, volume-mount shadowing).
- `[entrypoint] watchdog: model never became ready within Ns` means the
  in-container watchdog (see deploy-gcp.md items 32-33) killed it after
  real polling — the model never actually became ready in time, this is
  not a false alarm.

### `connectivity` — can micro-cosmos-web actually reach micro-cosmos-llmgateway?

This is the check that found the 2026-07-14 incident — run all of these
together, in order, rather than assuming a cold-start explanation from app
logs alone:

```bash
PROJECT=$(gcloud config get-value project)

# 1. Is micro-cosmos-llmgateway's ingress actually internal, and is IAM even the boundary?
gcloud run services describe micro-cosmos-llmgateway --region=europe-west4 \
  --format="yaml(metadata.annotations)"
gcloud run services get-iam-policy micro-cosmos-llmgateway --region=europe-west4

# 2. Does micro-cosmos-web have a VPC egress path onto Google's private network?
#    Look for run.googleapis.com/network-interfaces or vpc-access annotations —
#    their absence means outbound calls leave over the public internet.
gcloud run services describe micro-cosmos-web --region=europe-west4 \
  --format="yaml(spec.template.metadata.annotations,metadata.annotations)"

# 3. Ground truth: has micro-cosmos-llmgateway EVER logged an inbound request?
#    This log is generated by Cloud Run's front end before the container
#    is involved — zero entries here means requests aren't reaching the
#    service at all, which rules out cold-start/timing explanations
#    entirely and points at ingress/network instead.
gcloud logging read 'logName="projects/'"$PROJECT"'/logs/run.googleapis.com%2Frequests" AND resource.labels.service_name="micro-cosmos-llmgateway"' \
  --format="table(timestamp,httpRequest.status,httpRequest.requestUrl)" \
  --limit=50 --order=desc --freshness=7d

# 4. Cross-reference micro-cosmos-web's own readiness-poll timeline
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="micro-cosmos-web" AND textPayload=~"llmgateway.*ready|models ->"' \
  --format="table(timestamp,textPayload)" --limit=50 --order=desc --freshness=2h
```

Decision tree:
- Step 3 returns **zero entries ever** → network path problem, not timing.
  Check step 1 (ingress=internal) against step 2 (no VPC egress on the
  caller) — if ingress is internal and the caller has no
  `--network`/`--subnet`/`--vpc-egress`, that's the bug. Fix is Direct VPC
  egress on the caller (see deploy-gcp.md item 39), not relaxing the
  callee's ingress (usually blocked by org policy — check
  `constraints/run.allowedIngress` before proposing that as an option).
- Step 3 shows entries, all `404`, that eventually stop before a `200`
  appears → likely a genuine cold-start/timeout race (compare the last
  404 timestamp against the `llmgateway` scope's model-load timeline — did
  the model become ready *after* micro-cosmos-web's `llm_ready_timeout_seconds`
  window closed?).
- Step 3 shows a `401` → check the API key/`Authorization` header wiring
  (deploy-gcp.md item 26), not ingress.

## Report

State: which service, what the logs/config actually show (don't
paraphrase away specifics like exact error strings or annotation values),
which known pattern from `gcp-deployment.md`/`deploy-gcp.md` it matches (or
that it's new), and the concrete next diagnostic or fix step.
