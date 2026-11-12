---
name: vertex-ai-engine-support
description: llm_engine=vertex — Google Cloud Vertex AI as a third pipeline engine (Gemini only; Claude-on-Vertex explored and dropped), added 2026-09-08
metadata:
  type: project
---

Micro-Cosmos's pipeline can route `build_llm()` through Google Cloud
Vertex AI as a third `llm_engine` option alongside `lmstudio`/`vllm`. Unlike
those two, Vertex is a fully managed endpoint — no GPU-backed
`micro-cosmos-llmgateway` Cloud Run service is deployed for this option at all,
auth is ADC/IAM, and `driver.py`'s `_wait_for_llm_ready()` is skipped
entirely (no local GPU cold start to wait for).

**Scope note:** the original planning doc
(`product-roadmap-markup/Micro-Cosmos-with-LLMGateway-for-VertexAI-GCP.md`)
covered both Gemini and Claude via Vertex Model Garden. Claude-on-Vertex was
dropped mid-implementation (2026-09-08, user's call) after live testing
found the target project had no Anthropic Model Garden entitlement — see
"Claude-on-Vertex was explored and dropped" below. Everything shipped is
Gemini-only.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/settings.py` | `google_genai_use_vertexai`/`google_cloud_project`/`google_cloud_location` fields; `build_llm()` gained a `llm_engine == "vertex"` branch returning `LiteLlm(model=f"vertex_ai/{model_name}", vertex_project=..., vertex_location=..., drop_params=True, timeout=..., temperature=...)` — no `api_base`/`api_key`/`extra_body` (ADC auth, no Vertex equivalent to LM Studio's `num_ctx`) |
| `micro_cosmos/orchestration/driver.py` | `run_full_pipeline()` skips the LM-Studio-readiness poll when `llm_engine == "vertex"` |
| `docker-compose.yml` | Forwards `LLM_ENGINE`; un-commented `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION`; commented-out ADC bind mount (`~/.config/gcloud:/root/.config/gcloud:ro`) for local testing |
| `tests/test_settings_build_llm.py` | New — engine-branch assertions for lmstudio/vllm/vertex, verified against the real installed `LiteLlm` class's attribute shape (`.model` direct attr, everything else in `._additional_args`) |
| `deployment/deploy.py` | `LMSTUDIO_ENGINE=vertex` allow-listed; skips the GPU deploy step unconditionally for vertex (not `SKIP_LLM`-keyed); requires `MODEL_REASONING` explicitly (no `gpu_mod.DEFAULT_MODEL_ID`-style safe default exists for a managed endpoint) |
| `deployment/deploy_cloudrun-micro-cosmos-app.py` | `GOOGLE_GENAI_USE_VERTEXAI` env var now conditional on `llm_engine` (was hardcoded `FALSE`); added the previously-missing `GOOGLE_CLOUD_LOCATION` env var (a pre-existing gap, unrelated to vertex, fixed alongside it); prints a reminder for `llm_engine=vertex` that the runtime service account needs `roles/aiplatform.user` (or a further-scoped role) granted **manually** — see "IAM: deliberately not automated" below; `lmstudio_url` gets an inert placeholder for vertex instead of requiring `SKIP_LLM=true` |

## Live-verification findings (2026-09-08, against a real GCP project)

**1. Gemini-via-Vertex works cleanly, including tool-calling — the doc's flagged highest risk did not materialize.**
Ran the real `security_agent` (8 `FunctionTool`s, the highest tool-count/most
complex-schema agent in the pipeline) against `vertex_ai/gemini-2.5-flash`
with synthetic session state (no full pipeline run needed — just
`build_security_agent()` + a manually-seeded `InMemorySessionService`
session + `Runner.run_async()`, bypassing Observer/Cartographer/Architect
entirely to keep the API cost/time down). Result: all 8 tools called in the
correct ReACT sequence its own instructions specify, including
`submit_security_findings`'s nested `list[str]` arguments filled in
correctly. No hallucinated tool names, no degradation to plain-text-only.
ADK does print a `UserWarning` suggesting its native `Gemini(model=...)`
class over `LiteLlm(model="vertex_ai/...")` for better performance — this is
intentionally not adopted, since the whole point of `build_llm()` is one
uniform code path across all three engines; introducing a native ADK class
for Gemini-on-Vertex specifically would break that uniformity for a
performance nicety, not a correctness need.

**2. Dependencies: zero new ones needed for Gemini.** LiteLLM's
`vertex_ai/gemini-*` route works with what the project already has
(`litellm` + `google-auth`) — no `google-cloud-aiplatform` needed. (This
differs from the Claude-on-Vertex route, which does require
`google-cloud-aiplatform>=1.38` — see below. Since Claude was dropped,
`pyproject.toml` needed **no changes at all** for this feature, contradicting
the original doc's flagged dependency risk.)

**3. Real gotcha: ADC's baked-in quota project can silently differ from the
project you're actually trying to use, and it breaks aiplatform calls
specifically.** `gcloud config get-value project` and the ADC credential
file's `quota_project_id` are two *independent* settings — `gcloud auth
application-default login` does not automatically sync the quota project to
whatever `gcloud config set project` has. Symptom: `google.auth.default()`
resolves the right project name in its return tuple, but any Vertex AI call
routed through that credential object fails with `SERVICE_DISABLED` against
a **different**, unrelated project number (in this case, the wrong project
didn't even have `aiplatform.googleapis.com` enabled). Fix:
`gcloud auth application-default set-quota-project <project>`. Diagnostic
tip: if a Vertex/aiplatform call fails with `SERVICE_DISABLED` even though
you've confirmed the API is enabled on your target project, check
`python3 -c "import json; print(json.load(open('~/.config/gcloud/application_default_credentials.json'))['quota_project_id'])"`
before assuming the API enablement itself is wrong.

## IAM: deliberately not automated

An `ensure_vertex_ai_access()` helper was initially added to
`deploy_cloudrun-micro-cosmos-app.py`, mirroring the existing bucket-level
`ensure_examples_bucket()`/`ensure_runs_bucket()` pattern but as a
project-level `roles/aiplatform.user` grant. A background security review
correctly flagged the bare role as overly broad for a service account
fronting arbitrary untrusted source code, which was fixed with an IAM
condition scoping it to this project+region's `publishers/google/models/*`.

The whole helper was then removed at the user's explicit request (2026-09-08):
a deploy script silently mutating project-level IAM policy is a bigger ask
than the bucket-level grants (not every principal running `deploy.py` will
even have `resourcemanager.projects.setIamPolicy`), and granting Vertex AI
access is the kind of decision that should stay in the deploying
organization's hands, not something a shared framework's deploy script does
on their behalf. `deploy_micro_cosmos()` now only **prints** a reminder — with the
exact `gcloud projects add-iam-policy-binding ... --role=roles/aiplatform.user`
command — when `llm_engine == "vertex"`, and does nothing further. If this is
revisited, the IAM-condition-scoping approach above is still the right shape
for whoever runs that command by hand.

## Claude-on-Vertex was explored and dropped

Tested 5 Claude model IDs (`claude-3-haiku@20240307` — the oldest
Anthropic-on-Vertex model — through current `claude-sonnet-5@default`)
across 3 regions (`us-east5`, `europe-west1`, `global`) via both LiteLLM and
a direct `anthropic.AnthropicVertex` client using the **exact snippet copied
from the model's own GCP Console Model Garden page**. All returned an
identical 404 `NOT_FOUND — ... your project does not have access to it`.
That uniform failure across old/new models, multiple regions, and two
different client libraries (ruling out a naming/region/library bug on our
side) means: being able to *view* a partner model's page in Model Garden and
having live API access to it are two different things — Anthropic models
need a separate "Enable"/terms-acceptance click in the console per project,
which hadn't been done for the test project. If Claude-on-Vertex is revisited
later: (a) that console step is a prerequisite, done outside engineering's
control; (b) unlike Gemini, LiteLLM's Claude-via-Vertex route needs the
`vertexai` SDK (`pip install google-cloud-aiplatform>=1.38` — confirmed via
LiteLLM's own `ImportError` message, not assumed) even though the `anthropic`
package's own `AnthropicVertex` client does not; (c) `deploy.py`'s
`gpu_mod.DEFAULT_MODEL_ID`-style default doesn't apply to either partner
model — Vertex model IDs must be explicitly confirmed live, never hardcoded
into a plan.
