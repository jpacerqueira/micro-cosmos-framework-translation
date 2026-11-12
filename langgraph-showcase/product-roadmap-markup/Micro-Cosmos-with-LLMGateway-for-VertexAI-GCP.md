# Micro-Cosmos with LLMGateway for Vertex AI (GCP)

> **Superseded (2026-09-08).** This was the initial planning document for issue #36; the feature
> has since shipped with a scope narrower than what's proposed below. For what was actually built
> and why it diverged — Gemini-only (Claude-on-Vertex was evaluated live and dropped for lack of
> Model Garden entitlement), no dependency additions, no automated IAM granting — see
> [`transferable-skills/memory/vertex-ai-engine-support.md`](../transferable-skills/memory/vertex-ai-engine-support.md).
> The research below is kept as a historical record; do not treat it as the current design.

**Goal**: add a new, third "gateway type" to Micro-Cosmos's GCP deployment that routes the
11-agent pipeline's LLM calls through **Google Cloud Vertex AI**, supporting both **Gemini**
(Google's own models) and **Claude** (Anthropic's models, available on Vertex via its Model
Garden) — alongside the two existing self-hosted GPU engine types (LM Studio, vLLM).

This is a planning document only. No application code has been changed. Research was done
directly against the current codebase (not assumed from memory) — see file/line references
throughout. **Revision 2** (this version) corrects several inaccuracies found in Revision 1 and
adds a number of concrete gaps Revision 1 missed entirely — see "What changed in this revision"
at the end.

---

## 1. Current state

### "LLMGateway" is a deployment concept, not a code abstraction
There is no `LLMGateway` class or interface anywhere in `micro_cosmos/`. It's the Cloud Run **service
name** (`micro-cosmos-llmgateway`, renamed 2026-07-15 from `micro-cosmos-lmstudio` specifically because it's
engine-agnostic) for whichever GPU-backed inference software is deployed behind it — today, either
LM Studio or vLLM, both speaking an OpenAI-compatible `/v1` API. The actual swappable selector is
`micro_cosmos/settings.py:51`, `llm_engine: str = "lmstudio"` (or `"vllm"`).

### `build_llm()` has 12 call sites, not 1 — but the change is still contained to one function
`Settings.build_llm()` (`micro_cosmos/settings.py:180-218`) is **not** called from `pipeline.py`.
`pipeline.py` only imports agent-builder functions from `micro_cosmos/agents/`; each of the 11 real
pipeline agents independently constructs `LlmAgent(model=s.build_llm(role), tools=[FunctionTool(
...), ...])` in its own file:

| Agent file | Role | Tool count |
|---|---|---|
| `observer.py:59` | reasoning | 3 |
| `cartographer.py:36` | reasoning | 1 |
| `architect.py:115` | reasoning | 2 |
| `security.py:235` | reasoning | 8 (highest) |
| `feature_specifier.py:86` | reasoning | 2 |
| `code_writer.py:187` | reasoning | 6 |
| `skeptical_reviewer.py:91` | reasoning | 3 |
| `test_reviewer.py:108` | reasoning | 3 |
| `functional_reviewer.py:122` | reasoning | 6 |
| `writer.py:39` | fast | 1 |
| `reviewer.py:42` (PR reviewer) | fast | 1 |

There is also a **12th, orphaned** `LlmAgent` — `pattern.py`'s `build_pattern_agent()` — never
wired into `PipelinePhase` or called anywhere in `micro_cosmos/` or `tests/`. It's dead code, not one
of the 11 real pipeline phases; out of scope for this work.

**This is good news for scope**: every one of the 12 call sites just does `s.build_llm("reasoning"
/"fast")` and is completely agnostic to what engine that resolves to — as long as `build_llm()`
keeps returning an ADK-compatible model object, **none of these 12 agent files need to change**
for a new engine. The entire app-level change is contained inside `micro_cosmos/settings.py`.

### Vertex AI support today: documented, but dead code — and actively misleading
`GOOGLE_GENAI_USE_VERTEXAI` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` appear in
`docker-compose.yml`, `README.md`, and `deployment/deploy_cloudrun-micro-cosmos-app.py` — but
**`Settings` has no fields for any of them, and nothing ever reads them.** Grepping the entire
`micro_cosmos/` package for `vertexai`/`VertexAI`/`GOOGLE_GENAI_USE_VERTEXAI` returns zero hits.

This is more than aspirational documentation — it is currently a live footgun:
- `deploy_cloudrun-micro-cosmos-app.py:261` **hardcodes** `GOOGLE_GENAI_USE_VERTEXAI=FALSE`
  unconditionally in the `env_vars` list built by `deploy_service()`, with no parameter or env
  override path.
- `GOOGLE_CLOUD_LOCATION` is **never set on `micro-cosmos-web` at all** — only `GOOGLE_CLOUD_PROJECT`
  is included in that same env-var list. Even if the `FALSE` hardcode were fixed, location would
  still be missing.
- Root `README.md`'s "Vertex AI / Gemini (production)" section instructs users to set
  `GOOGLE_GENAI_USE_VERTEXAI=TRUE` and run `python deployment/deploy.py` — following those
  instructions today silently does nothing, because of the hardcode above. `deployment/README.md`
  has no dedicated Vertex section, but its manual `gcloud run deploy micro-cosmos-web` example bakes in
  the same `GOOGLE_GENAI_USE_VERTEXAI=FALSE` literal.
- `docker-compose.yml` has `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` present but
  **commented out** by default, and never forwards `LLM_ENGINE` to the container at all — a local
  `docker compose up` always resolves `llm_engine` to `Settings`'s default (`"lmstudio"`)
  regardless of what's actually configured, unless a developer manually adds the line.

(README.md and deployment/README.md have been corrected as part of this same piece of work — see
§7 below — so they no longer instruct users toward a path that does nothing.)

### `chat.py` is a second, fully independent LLM code path — not just a "precedent"
`micro_cosmos/retrieval/chat.py:293-317` (the ASK tab, explicitly decoupled from the ADK pipeline
session per `CLAUDE.md`) calls `litellm.completion()` directly, with its own routing logic:

```python
if settings.anthropic_api_key and model_name.startswith("claude-"):
    call_kwargs["model"] = f"anthropic/{model_name}"
    call_kwargs["api_key"] = settings.anthropic_api_key
else:
    call_kwargs["model"] = f"openai/{model_name}"
    call_kwargs["api_base"] = settings.llm_base_url
    call_kwargs["api_key"] = settings.llm_api_key
```

This confirms the codebase already speaks LiteLLM's `provider/model-id` convention — the same
shape `vertex_ai/claude-*` would need — but **this logic is entirely separate from
`build_llm()`**, which has no Anthropic or Vertex branch at all today. A Vertex rollout for the
pipeline touches `build_llm()` only; `chat.py`'s independent Anthropic-direct-API-key routing is
untouched (see §3.7 — this is a deliberate scope decision, not an oversight).

### Claude-on-Vertex is a LiteLLM/SDK matter, not an ADK-native one
ADK's native Gemini client (`google-genai`) has first-class Vertex AI support, but no support for
Anthropic's partner-model request shape on Vertex Model Garden. Since this pipeline already routes
every agent through LiteLLM (not ADK's native client), **this is good news**: LiteLLM already
knows how to speak `vertex_ai/gemini-*` and `vertex_ai/claude-*` — both would go through the same
`LiteLlm` wrapper this codebase already uses everywhere, just with different construction
arguments (`vertex_project`/`vertex_location` + GCP Application Default Credentials, instead of
`api_base`/`api_key`).

### No secrets-manager abstraction exists — ADC fits without new plumbing
Every credential in `Settings` (`llm_api_key`, `anthropic_api_key`, `gate_token`,
`session_secret_key`) is a plain pydantic string field read from env/`.env` — there is no Secret
Manager client, Vault, or KMS wrapper anywhere in the codebase. This confirms (not just assumes)
that Vertex's ADC auth model needs **zero** new secret-handling plumbing: `vertex_project`/
`vertex_location` are just two more plain string config fields, and auth flows through whatever
identity the Cloud Run service already runs as.

### No existing test coverage for engine selection
`grep -rn "llm_engine|build_llm|LiteLlm|litellm" tests/` returns zero hits. Every existing test
dodges LLM calls entirely via `Settings(skip_llm=True, ...)` +
`monkeypatch.setattr(settings_mod, "_settings", s)` (e.g. `tests/test_pipeline.py:17-19`). There
is no "assert `build_llm()` returns the right config for engine X" test to extend today — a
`vertex` option needs net-new tests, not an extension of an existing pattern (see §3.8).

### `/healthz` does no LLM-engine check; the only readiness logic is LM-Studio-native and un-branched
`micro_cosmos/web/app.py:1506`'s `/healthz` returns static `{"status": "ok", "active_runs": ...}` —
no parity work is needed there for a new engine. The actual LLM-readiness logic lives in
`driver.py`'s `_wait_for_llm_ready()` (lines 41-140), called once before a fresh run's
Observer phase (`driver.py:217-236`). It has **zero existing per-engine branching** today — it
runs identically for `lmstudio` and `vllm`, distinguishing them only by which HTTP endpoint (LM
Studio's native `/api/v0/models` vs. the OpenAI-compatible `/v1/models` fallback) responds 200.
Adding `vertex` means introducing the **first** engine-conditional branch here, not extending one
that already exists.

### A key structural difference from the existing two engine types
LM Studio and vLLM both require **a GPU-backed Cloud Run service** (`micro-cosmos-llmgateway`) that
`micro-cosmos-web` talks to. **Vertex AI needs no such service at all** — it's a fully managed Google
endpoint; `micro-cosmos-web` would call it directly via ADC. Adding this gateway type actually
*simplifies* the deployment topology for anyone who chooses it (one fewer Cloud Run service, no
GPU quota/cost to manage) — worth stating plainly since the existing "LLMGateway" naming implies a
service that, for this option, wouldn't need to exist.

### Dependencies
`pyproject.toml` currently has `google-adk[extensions]>=1.18.0` and `litellm>=1.40.0`. **No**
`anthropic` package and **no** `google-cloud-aiplatform` package are direct dependencies yet —
LiteLLM's `vertex_ai` provider needs Google auth libraries (and likely `google-cloud-aiplatform`
for Model Garden partner-model routing); this needs verifying against the actual resolved
dependency tree at implementation time, not assumed.

---

## 2. Models to support

**Anthropic Claude (current generation, confirmed)**:
- `claude-opus-5` — highest capability
- `claude-sonnet-5` — balanced default (this pipeline's likely default role model)
- `claude-haiku-4-5-20251001` — fastest/cheapest

**Google Gemini**: use whichever is Google's current flagship model in Vertex AI's Model Garden at
implementation time — **do not hardcode a specific version in this plan**; Gemini model IDs and
availability rotate independently of this project and must be confirmed directly against the
target GCP project's Vertex AI Model Garden listing (`gcloud ai models list` / the Vertex console)
when this is actually built, not assumed from a plan written today.

Both should be configurable via the existing `MODEL_REASONING`/`MODEL_FAST` settings (already
per-role, already exist) — no new "which model" concept is needed, only a new "which engine/auth
shape serves this model ID" concept.

---

## 3. Design

### 3.1 New `llm_engine` value: `"vertex"`
Extend the existing 2-value engine selector to 3: `"lmstudio"` (default) / `"vllm"` / `"vertex"`.

### 3.2 `Settings` — add the 3 currently-dead fields for real
```python
google_genai_use_vertexai: bool = False
google_cloud_project: str = ""
google_cloud_location: str = "us-central1"
```
Reusing these exact names is deliberate: they make the already-existing (currently false)
docker-compose/README references true instead of inventing new ones.

### 3.3 `build_llm()` — one new branch, no other file changes
```python
if self.llm_engine == "vertex":
    return LiteLlm(
        model=f"vertex_ai/{model_name}",
        vertex_project=self.google_cloud_project,
        vertex_location=self.google_cloud_location,
        drop_params=True,
        timeout=self.llm_timeout,
        temperature=self.model_temperature,
    )
```
No `api_base`/`api_key` (auth flows through ADC / the Cloud Run service account's IAM role — see
§3.5) and no `extra_body` (`num_ctx` has no Vertex equivalent — it's an LM Studio/llama.cpp
KV-cache parameter with no meaning against a managed endpoint). Model-ID prefix
(`vertex_ai/claude-*` vs `vertex_ai/gemini-*`) determines which partner backend LiteLLM actually
calls; both share the same `vertex_ai/` LiteLLM provider, so this is one branch, not two — matching
the existing `if llm_engine == "lmstudio"` / implicit-else-vllm shape. As established in §1, this
is the **only** code change needed for the 11 real pipeline agents to start using Vertex; none of
`micro_cosmos/agents/*.py` needs to change.

### 3.4 `driver.py`'s `_wait_for_llm_ready()`
Must no-op/skip entirely when `llm_engine == "vertex"` — there's no local GPU cold start to wait
for; Vertex is always "ready" from this pipeline's perspective (a real API call is still the true
readiness check, exactly like it already is for the other two engines, but the pre-flight
model-loaded polling loop is meaningless for a managed endpoint). This is the first per-engine
branch introduced at this call site — today it runs unconditionally regardless of `llm_engine`.

### 3.5 Deploy scripts
- **`deploy_cloudrun-micro-cosmos-app.py`**: make the `GOOGLE_GENAI_USE_VERTEXAI=FALSE` hardcode
  (line 261) conditional on the chosen engine, and **add the currently-missing
  `GOOGLE_CLOUD_LOCATION` env var** to the same `env_vars` list (line ~262) — today only
  `GOOGLE_CLOUD_PROJECT` is set, a pre-existing gap independent of whether Vertex ships.
- **IAM — genuinely new, not a copy of an existing pattern**: no project-level IAM binding exists
  in any deploy script today. The only IAM calls anywhere are two **bucket-level**
  `roles/storage.objectAdmin` grants (`ensure_examples_bucket()` / `ensure_runs_bucket()` in
  `deploy_cloudrun-micro-cosmos-app.py:139-205`, both following the same `gcloud storage buckets
  add-iam-policy-binding` + try/except-already-exists shape). Add a new `ensure_vertex_ai_access()`
  helper mirroring that shape at the **project** level:
  ```bash
  gcloud projects add-iam-policy-binding $PROJECT \
    --member=serviceAccount:$SERVICE_ACCOUNT \
    --role=roles/aiplatform.user
  ```
  Call it only when `engine == "vertex"`.
- **`deploy.py`**: add `"vertex"` to the engine allow-list (currently `("lmstudio", "vllm")`,
  `deploy.py:91-97`, which hard-rejects anything else). The existing "skip GPU deploy" branch
  (`deploy.py:122-133`) is keyed on `SKIP_LLM`, **not** on engine choice — today `SKIP_LLM=false`
  always deploys a GPU service for both existing engines. A `vertex` engine must skip the GPU
  deploy **unconditionally**, regardless of `SKIP_LLM` — this is a materially different condition
  than exists today, not a reuse of the current one.
- **Model-ID resolution has no `vertex` equivalent today.** `deploy.py:100-111`'s drift-prevention
  pattern (added after a real 2026-07-11 incident — see `transferable-skills/memory/
  gcp-deployment.md:1318`) resolves `MODEL_REASONING`/`MODEL_FAST` once against
  `gpu_mod.DEFAULT_MODEL_ID` and passes it to both deploys, because vLLM rejects any model ID it
  wasn't launched with. There is no `gpu_mod` for Vertex — a `vertex` branch needs its own
  resolution path; the real constraint isn't "what was the GPU launched with" but "is this model
  ID actually enabled in this project's Vertex Model Garden," which can only be verified live
  (`gcloud ai models list`), not defaulted the way `gpu_mod.DEFAULT_MODEL_ID` is.
- **Regional availability — a brand-new deployment-topology risk GPU engines never had.**
  `deploy.py:83` defaults `region = "europe-west4"`, chosen purely for GPU quota reasons
  (`deploy_cloudrun-micro-cosmos-app.py:81`'s own comment: "match the LLMGateway service's region").
  Anthropic's Claude models on Vertex Model Garden are only enabled in a subset of Vertex regions
  — GPU quota and partner-model regional allowlisting are two *independent* constraints, and
  nothing in the deploy scripts today has ever had to reconcile them. Confirm live against the
  target project (`gcloud ai models list` / Vertex console) at implementation time — do not
  silently inherit `europe-west4`.
- **Naming-collision precedent worth carrying forward**: the vLLM engine swap had a real incident
  where `VLLM_`-prefixed custom env vars collided with vLLM's own env-var scanner (false-positive
  "Unknown environment variable" warnings), fixed by renaming to `LMSTUDIO_*`
  (`transferable-skills/memory/gcp-deployment.md:1621`). If any new custom env var beyond the 3
  already-named `GOOGLE_*` ones is introduced for Vertex, check it doesn't collide with Google's
  own ADC/genai library env-var scanning before naming it.

### 3.6 Local dev verification path (new — not in Revision 1)
`docker-compose.yml` never forwards `LLM_ENGINE` to the container at all today, so a local
`docker compose up` always resolves to `Settings`'s default (`"lmstudio"`) regardless of intent.
Add `LLM_ENGINE: ${LLM_ENGINE:-lmstudio}`, and un-comment the existing (currently commented-out)
`GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` lines, so the new `vertex` branch can be exercised
locally against a real Vertex project via Application Default Credentials
(`gcloud auth application-default login`) **before** any Cloud Run deploy — this de-risks the
tool-calling verification step (§4.3) by giving it a fast local iteration loop instead of requiring
a full deploy for every test.

### 3.7 ASK tab (`chat.py`) — deliberate scope decision, not an oversight
`chat.py`'s existing standalone Anthropic-direct-API-key path (§1) is left as-is. This means, after
this work ships, there will be **two independent ways Claude gets called** in this codebase: direct
Anthropic API for the ASK tab, Vertex-routed for the pipeline. This is a deliberate, documented
inconsistency, not an oversight — the ASK tab's path already works and is isolated from the
pipeline session per `CLAUDE.md`. Revisit only if there's a concrete reason (e.g. wanting one
billing/quota surface instead of two); not a blocker for this work.

### 3.8 Test strategy (new — not in Revision 1)
No existing test mocks LiteLLM or exercises `build_llm()`/`llm_engine` in any form — this needs
net-new coverage, not an extension. Add `tests/test_settings_build_llm.py` asserting the exact
`LiteLlm(...)` construction arguments `build_llm()` produces for each of the three `llm_engine`
values (`lmstudio`, `vllm`, `vertex`), following the existing `Settings(...)` +
`monkeypatch.setattr(settings_mod, "_settings", s)` construction pattern used everywhere else in
`tests/`. No real network calls or LiteLLM response mocking needed — just inspecting the
constructed object's attributes (`model`, `vertex_project`, `vertex_location`, absence of
`api_base`/`api_key`/`extra_body` for the vertex case).

---

## 4. Directly transferable lessons from the LM Studio → vLLM engine swap

This codebase has already done "add a new engine type" once; the same lessons apply again here:

1. **Readiness-check divergence** — covered in §3.4.
2. **Model-ID alignment risk across independently-configured deploy paths** — covered in §3.5,
   with the added twist that Vertex has no `gpu_mod` to resolve against at all, unlike the
   vLLM case this lesson originally came from.
3. **Tool-calling must be explicitly verified, never assumed from provider branding** — vLLM
   needed explicit `--enable-auto-tool-choice --tool-call-parser <name>` flags or ADK's
   `FunctionTool`-based agents silently got plain text back instead of structured tool calls. All
   11 real pipeline agents are `FunctionTool` users (see the table in §1; `security.py` (8 tools),
   `code_writer.py` and `functional_reviewer.py` (6 tools each) are the highest-risk agents to
   verify first, since they have the most JSON schema surface for Gemini's function-calling
   support to potentially choke on — Gemini's function-calling schema has known quirks, e.g.
   limited `anyOf`/certain JSON Schema construct support). **This remains the single highest-risk
   unknown in this whole plan**: confirm LiteLLM's `vertex_ai/claude-*` and `vertex_ai/gemini-*`
   paths correctly round-trip ADK's function-calling schema before relying on either for real
   pipeline runs, not just chat-style single-turn calls.
4. **Regional/model allowlisting is a new axis this codebase hasn't had to handle before** — see
   §3.5's regional-availability point. Neither prior engine swap had to consider "is this model
   even enabled in this region for this project," since GPU quota was the only regional constraint
   ever encountered.

---

## 5. Effort estimate

Revision 1 estimated ~4–5 days assuming this was purely additive. Several gaps found in this
revision (IAM, regional availability, local dev wiring, Vertex-specific model-ID resolution, and
zero existing test infrastructure) were entirely unaccounted for there:

| Item | Size | Estimate |
|---|---|---|
| `Settings`: add the 3 real fields + `llm_engine="vertex"` value (§3.2) | XS | 1–2 hours |
| `build_llm()`: new Vertex branch (§3.3) | S | half a day |
| `driver.py`: skip readiness-wait for `vertex` engine (§3.4) | XS | 1 hour |
| Local dev path — `docker-compose.yml` wiring (§3.6) | XS | 1–2 hours |
| Unit tests for `build_llm()` per engine (§3.8) | S | half a day |
| Dependency verification/addition (`google-cloud-aiplatform` and/or LiteLLM's `vertex_ai` extra — confirm against the resolved tree, don't assume) | S | half a day |
| **Tool-calling verification for both Gemini-via-Vertex and Claude-via-Vertex** against real ADK `FunctionTool` agents, prioritizing `security.py`/`code_writer.py`/`functional_reviewer.py` | M | 1 day — biggest risk in this plan, needs a real GCP project with both models enabled |
| Deploy scripts: conditional `GOOGLE_GENAI_USE_VERTEXAI`, missing `GOOGLE_CLOUD_LOCATION` fix, new `ensure_vertex_ai_access()` IAM step, `deploy.py`'s engine-aware GPU-skip (not `SKIP_LLM`-keyed), Vertex-specific model-ID resolution, region-availability confirmation | M | 1.5–2 days |
| ASK tab: decision only (recommend: no change, documented as deliberate — §3.7) | — | 0 |
| Docs: `CLAUDE.md`, a new `transferable-skills/memory/*.md` entry following the LM Studio→vLLM engine-swap writeup style | S | half a day |
| End-to-end live verification (real pipeline run against Vertex, both a Gemini-backed and a Claude-backed configuration) | M | 1 day |

**Total engineering estimate: ~6–8 days** (revised up from Revision 1's ~4–5 days).

**Not an engineering estimate, but a real dependency**: Anthropic's Claude models on Vertex AI
Model Garden require the target GCP project/org to have that partner model **enabled and
allowlisted in the chosen region** — this is a GCP console/administrative step, sometimes with its
own approval lead time, entirely outside engineering control, and now also gated on the
region-availability question in §3.5 (not just "is it enabled for this project" but "is it enabled
for this project *in this region*"). Confirm this access exists (or request it) *before*
scheduling the engineering work above, since the tool-calling verification step (the highest-risk
item) can't start without it.

---

## 6. Recommended order of work

1. Confirm Claude-on-Vertex Model Garden access is enabled for the target GCP project **and
   region** (external dependency, now sharper than Revision 1's version — see §3.5/§5 — start
   this first, it can gate everything else).
2. `Settings` fields + `build_llm()` Vertex branch (§3.2–3.3), plus the local dev wiring (§3.6) and
   unit tests (§3.8) — can be built, unit-tested, and manually exercised locally via ADC with
   Gemini-via-Vertex alone first, since that access is more likely to already exist and this path
   needs no GCP deploy at all to validate.
3. Tool-calling verification against a real Vertex-backed pipeline run, Gemini first (lower risk),
   then Claude once Model Garden access is confirmed — prioritize the highest-tool-count agents
   (`security.py`, `code_writer.py`, `functional_reviewer.py`) since they have the most schema
   surface to break.
4. Deploy script changes (§3.5) — only once the app-level code path is proven to work. Confirm
   regional availability before wiring the IAM step, since a region change here would also affect
   the GPU engines' quota assumptions if the region is shared.
5. Docs: `CLAUDE.md` + a new `transferable-skills/memory/*.md` entry, following the same style as
   the LM Studio→vLLM engine-swap writeup. (Root `README.md`/`deployment/README.md` were already
   corrected as part of this same body of work — see §7 — independent of whether the engineering
   itself has shipped yet.)
6. Decide on the ASK tab question (§3.7) as a fast follow, not a blocker — current recommendation
   is no change.

---

## 7. Documentation corrected as part of this revision

The following were corrected directly (not just flagged) as part of producing this revision, since
they described a working deployment path that does not exist and would mislead anyone following
them today:

- Root `README.md`: intro line (no longer claims Vertex AI works "in production"), the config
  table's Vertex row (replaced with a callout that it has no effect today), the "Vertex AI /
  Gemini (production)" subsection (reframed as "planned, not yet implemented"), and the
  "Deployment — Cloud Run + Vertex AI" section heading/instructions (renamed to "Deployment —
  Cloud Run", instructions corrected to describe the actual LM Studio/vLLM deploy path).
- `deployment/README.md`: added an explanatory note above the manual `gcloud run deploy
  micro-cosmos-web` example clarifying that `GOOGLE_GENAI_USE_VERTEXAI=FALSE` is intentionally
  hardcoded (not a copy-paste error) and that `GOOGLE_CLOUD_LOCATION` is deliberately absent.

No application code (`micro_cosmos/`, `deployment/*.py`, `docker-compose.yml`) was changed — the
engineering work described in §3–§6 above remains future work.

---

## What changed in this revision

Corrections to Revision 1:
1. `build_llm()` has 12 call sites across `micro_cosmos/agents/*.py` (11 real + 1 orphaned), not 1 call
   site in `pipeline.py` — the scope conclusion (single-function change) still holds, but the
   original file/line claim was wrong.
2. `chat.py`'s Claude routing was framed as a "precedent" the new work builds on; it's actually a
   fully separate, still-independent code path that this work does not touch or unify with.
3. Added explicit confirmation that no secrets-manager abstraction exists (ADC fits cleanly) and
   that zero test coverage exists for engine selection (net-new tests needed, §3.8).
4. Added explicit confirmation that `/healthz` needs no changes, but `_wait_for_llm_ready()`
   has zero existing per-engine branching (§3.4 is the first one, not an extension).

New gaps found (absent from Revision 1 entirely):
5. `GOOGLE_CLOUD_LOCATION` is never set on `micro-cosmos-web` today, independent of the `vertex` work.
6. `docker-compose.yml` never forwards `LLM_ENGINE` locally — added a local dev path (§3.6).
7. No project-level IAM binding exists in any deploy script today — the `roles/aiplatform.user`
   grant is genuinely new plumbing, not a copy of the existing bucket-level pattern.
8. `deploy.py`'s GPU-skip logic is keyed on `SKIP_LLM`, not engine — vertex needs a materially
   different, engine-aware condition.
9. No `gpu_mod`-equivalent exists for Vertex's model-ID resolution — needs its own path.
10. Regional availability of Claude on Vertex Model Garden is a new deployment-topology risk the
    two GPU engines never had to consider; the default deploy region was chosen for GPU quota
    reasons only.
11. Root `README.md` and `deployment/README.md` described a deployment path that cannot work
    today (§1) — corrected directly rather than left as a known issue (§7).

Effort estimate revised from ~4–5 days to ~6–8 days to account for gaps 5–11.
