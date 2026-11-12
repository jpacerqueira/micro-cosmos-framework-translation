# Micro-Cosmos with LLMGateway for Vertex AI (GCP)

**Goal**: add a new, third "gateway type" to Micro-Cosmos's GCP deployment that routes the
11-agent pipeline's LLM calls through **Google Cloud Vertex AI**, supporting both **Gemini**
(Google's own models) and **Claude** (Anthropic's models, available on Vertex via its Model
Garden) — alongside the two existing self-hosted GPU engine types (LM Studio, vLLM).

Revision 2: re-planned against LiteLLM's official ADK integration tutorial
(https://docs.litellm.ai/docs/tutorials/google_adk), which changes the recommended architecture —
see §3. Research was done directly against the current codebase and that tutorial, not assumed
from memory; file/line references and exact quotes throughout.

---

## 1. Current state (unchanged from revision 1, still accurate)

### "LLMGateway" is a deployment concept, not a code abstraction
There is no `LLMGateway` class or interface anywhere in `micro_cosmos/`. It's the Cloud Run **service
name** (`micro-cosmos-llmgateway`, renamed 2026-07-15 from `micro-cosmos-lmstudio` specifically because it's
engine-agnostic) for whichever GPU-backed inference software is deployed behind it — today, either
LM Studio or vLLM, both speaking an OpenAI-compatible `/v1` API. The actual swappable selector is
`micro_cosmos/settings.py:51`, `llm_engine: str = "lmstudio"` (or `"vllm"`), read in exactly one place:
`Settings.build_llm()` (`micro_cosmos/settings.py:180-218`), which conditionally adds an
LM-Studio-specific `extra_body={"num_ctx": ...}` — vLLM's stricter schema validation would reject
that field outright if sent unconditionally.

### Vertex AI support today: documented, but dead code
`GOOGLE_GENAI_USE_VERTEXAI` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` appear in
`docker-compose.yml`, `README.md`, and `deployment/deploy_cloudrun-micro-cosmos-app.py` — but
**`Settings` has no fields for any of them, and nothing ever reads them.**
`deploy_cloudrun-micro-cosmos-app.py:261` even **hardcodes** `GOOGLE_GENAI_USE_VERTEXAI=FALSE`
unconditionally on every deploy. Every one of this pipeline's 11 agents is constructed as
`LlmAgent(model=settings.build_llm(role))`, and `build_llm()` **always** wraps the model in a
`google.adk.models.lite_llm.LiteLlm(...)` object pointed at a self-hosted `api_base`/`api_key` —
never a bare Gemini model-ID string — so even if the three env vars were read, ADK's native Vertex
path would never actually be reached today.

### A working Claude-via-LiteLLM precedent already exists — but outside the pipeline
`micro_cosmos/retrieval/chat.py:293-317` (the ASK tab, explicitly decoupled from the ADK pipeline
session per `CLAUDE.md`) already calls `litellm.completion()` directly with a
`model_name.startswith("claude-")` branch, prefixing the model as `anthropic/<model>` with a
direct Anthropic API key — confirming this codebase already speaks LiteLLM's `provider/model-id`
convention. This logic is entirely separate from `build_llm()` and the 11-agent pipeline.

### Dependencies
`pyproject.toml` currently has `google-adk[extensions]>=1.18.0` and `litellm>=1.40.0`. No
`anthropic` package and no `google-cloud-aiplatform` package are direct dependencies yet.

---

## 2. What LiteLLM's own ADK tutorial actually shows (new — this changes the recommended design)

Fetched directly from https://docs.litellm.ai/docs/tutorials/google_adk. Key findings:

1. **The wrapper class is `google.adk.models.lite_llm.LiteLlm`** — matches what `build_llm()`
   already uses. Confirmed, no change needed here.
2. **Gemini is NOT wrapped in `LiteLlm` at all in the official pattern.** The tutorial passes a
   bare model string (`model=MODEL_GEMINI_PRO`) straight to `LlmAgent`, relying on ADK's *native*
   Gemini client and plain `GOOGLE_API_KEY` (or, for Vertex, ADK's native
   `GOOGLE_GENAI_USE_VERTEXAI`/`GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` auto-detection — not
   shown in this specific tutorial, but it's the same three env vars already dead-coded into this
   repo's `docker-compose.yml`/README). **This means Gemini-via-Vertex needs zero LiteLLM
   involvement** — it's purely an ADK-native code path.
3. **Anthropic is shown only as a direct API-key call**: `LiteLlm(model="anthropic/claude-3-sonnet-20240229")`
   with `ANTHROPIC_API_KEY` — not `vertex_ai/claude-*`, and **no Vertex AI example of any kind
   appears in this tutorial at all.** No `vertex_project`/`vertex_location`/`api_base`/`api_key`
   constructor arguments are demonstrated for any provider — the tutorial's `LiteLlm()` calls take
   only `model=`. This means the `vertex_project`/`vertex_location` kwargs assumed in revision 1 of
   this plan are **not validated by this specific integration doc** — they exist in LiteLLM's own
   general provider docs, but reaching them through the ADK wrapper specifically is comparatively
   less-trodden ground than this plan first assumed. Worth budgeting real trial-and-error time for,
   not treating as a known-good recipe.
4. **The tutorial's own recommended pattern for "many providers behind one consistent interface" is
   the LiteLLM Proxy**, not per-provider kwargs in application code:
   ```python
   os.environ["LITELLM_PROXY_API_KEY"] = "your-litellm-proxy-api-key"
   os.environ["LITELLM_PROXY_API_BASE"] = "your-litellm-proxy-url"
   litellm.use_litellm_proxy = True
   ```
   A LiteLLM Proxy is a small standalone server (the open-source `litellm[proxy]` package) that
   itself fronts many providers — OpenAI, Anthropic, **and Vertex AI (Gemini + Claude Model
   Garden)** — behind one OpenAI-compatible `/v1` endpoint, configured via a YAML file, with the
   proxy holding all provider credentials so the calling app only ever needs one `api_base` +
   one proxy API key.
5. No explicit tool-calling caveats are stated in this tutorial (a `get_weather()` `FunctionTool`
   example is shown working for all three providers) — but it's a single-turn toy example, not
   proof against this pipeline's much heavier structured-output/`FunctionTool` usage across 11
   agents. Treat as "no known issue," not "verified for our use case."

---

## 3. Design — three options, with a recommendation

### Option A — Recommended: a LiteLLM Proxy as the new "vertex" LLMGateway variant

Deploy a small, **CPU-only** Cloud Run service running the open-source LiteLLM Proxy
(`litellm[proxy]`), configured via a `litellm_config.yaml` that maps simple model aliases (e.g.
`gemini-latest`, `claude-latest`) to their real backends:
```yaml
model_list:
  - model_name: gemini-latest
    litellm_params:
      model: vertex_ai/<gemini-model-id>       # confirm exact ID against Model Garden at build time
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/GOOGLE_CLOUD_LOCATION
  - model_name: claude-latest
    litellm_params:
      model: vertex_ai/claude-opus-5           # or claude-sonnet-5 / claude-haiku-4-5-20251001
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/GOOGLE_CLOUD_LOCATION
```
`micro-cosmos-web`'s `build_llm()` needs **no new branch at all** — it points its existing
`api_base`/`api_key` construction at the proxy's URL and a proxy virtual key, exactly the same
shape already used for LM Studio/vLLM. The proxy's own service account holds `roles/aiplatform.user`
and talks to Vertex; `micro-cosmos-web` never touches Vertex-specific auth directly.

**Why this is the recommended option**:
- Matches this codebase's own existing design philosophy exactly — `micro-cosmos-llmgateway` was
  renamed specifically to be *engine-agnostic*; a LiteLLM Proxy extends that same idea to Vertex
  with the same OpenAI-compatible contract every other engine already uses.
- Zero changes to `build_llm()`, `driver.py`'s readiness check (the proxy exposes the same generic
  `/v1/models` endpoint the vLLM fallback path already handles), or any of the 11 agent files —
  the lowest-regression-risk option of the three.
- One consistent request/auth shape for both Gemini *and* Claude, avoiding the asymmetric
  special-casing Option C below would require.
- This is LiteLLM's own officially documented pattern for multi-provider setups, not something
  assembled from partial signals.

**Trade-off**: introduces one new, small, always-on Cloud Run service (CPU-only, no GPU quota —
materially cheaper and simpler to provision than the existing GPU LLMGateway options, but still a
new moving part with its own container image, health checks, and IAM to deploy and monitor).

### Option B — Direct in-process LiteLLM branch in `build_llm()` (revision 1's original design)

Extend `build_llm()` with a new `llm_engine == "vertex"` branch constructing
`LiteLlm(model="vertex_ai/claude-*", vertex_project=..., vertex_location=...)` directly inside
`micro-cosmos-web`, no separate proxy service. Simpler topology (no new service to deploy), but **not
validated by LiteLLM's own ADK tutorial** (§2, point 3) — higher implementation risk, more
trial-and-error, and puts Vertex ADC credentials directly on the main application's service
account rather than isolated to a small dedicated proxy.

### Option C — Gemini-only shortcut (not recommended, given both models are required)

Since §2 confirms Gemini needs no LiteLLM involvement in ADK, the cheapest possible partial path is
fixing the already-dead `GOOGLE_GENAI_USE_VERTEXAI`/`GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION`
fields and passing a bare Gemini model string when `llm_engine == "vertex"`. This would leave
Claude unsupported (needs Option A or B on top), creating an asymmetric hybrid. **Not chosen**
here since the requirement is both models, uniformly, but worth knowing this shortcut exists if
scope is ever trimmed to Gemini-only.

### `driver.py`'s `_wait_for_llm_ready()`
Under Option A: likely **no change needed** — the proxy exposes the same generic `/v1/models`
endpoint the existing vLLM fallback already handles. Under Option B: must no-op/skip entirely for
`vertex`, since there's no local GPU cold start to wait for and no generic model-list endpoint to
poll in the same way.

### Deploy scripts (Option A)
- New `deployment/deploy_cloudrun-litellm-vertex-proxy.py`, modeled on the existing
  `deploy_cloudrun-lmstudio-llms.py`/`deploy_cloudrun-vllm-llms.py` pair but deploying a CPU-only
  service from the official LiteLLM proxy container image plus the `litellm_config.yaml` above —
  no GPU flags, no model-weights download step (a materially simpler script than its two GPU
  siblings).
- `deploy_cloudrun-micro-cosmos-app.py`: `GOOGLE_GENAI_USE_VERTEXAI=FALSE` hardcode becomes conditional;
  when the engine is `vertex`, point `LLM_BASE_URL`/`LLM_API_KEY` at the new proxy
  service's URL/virtual-key instead of the GPU LLMGateway.
- `deploy.py`: third engine branch. When `vertex` is chosen, deploy the LiteLLM proxy service
  instead of provisioning the GPU `micro-cosmos-llmgateway` service — a genuinely different deploy
  topology, not just a new env var.
- Apply the same model-ID-alignment safeguard the LM Studio→vLLM engine swap already needed (§4) —
  one authoritative model-alias resolved by `deploy.py`, written into both the proxy's config and
  `micro-cosmos-web`'s `MODEL_REASONING`/`MODEL_FAST`, so they can't silently drift.

### ASK tab (`chat.py`)
Recommend leaving its existing standalone Anthropic-direct-API-key path unchanged initially — it
already works independently of this change and isn't blocked by it. Revisit only if there's a
concrete reason to unify billing/quota onto the new Vertex path.

---

## 4. Directly transferable lessons from the LM Studio → vLLM engine swap

Still fully applicable regardless of which option above is chosen:

1. **Readiness-check divergence** — covered above per option.
2. **Model-ID alignment risk across independently-configured deploy paths** — vLLM hard-rejects
   any model ID other than what it was launched with; the same risk applies to a Vertex Model
   Garden project not having a given model enabled/allowlisted. Fix identically: one authoritative
   model ID/alias resolved once by `deploy.py`, not defaulted independently in multiple places.
3. **Tool-calling must be explicitly verified, never assumed from provider branding** — vLLM
   needed explicit `--enable-auto-tool-choice` flags or ADK's `FunctionTool`-based agents silently
   got plain text back instead of structured tool calls. Nearly every one of this pipeline's 11
   agents is a `FunctionTool` user, and §2 point 5 above confirms the LiteLLM ADK tutorial's own
   tool-calling example is a single-turn toy, not evidence for this pipeline's usage pattern —
   **this remains the single highest-risk unknown in this whole plan**, for either option.

---

## 5. Models to support

**Anthropic Claude (current generation, confirmed)**: `claude-opus-5` (highest capability),
`claude-sonnet-5` (balanced default), `claude-haiku-4-5-20251001` (fastest/cheapest).

**Google Gemini**: use whichever is Google's current flagship model in Vertex AI's Model Garden at
implementation time — deliberately not hardcoded here; confirm directly against the target GCP
project's Vertex AI Model Garden listing (`gcloud ai models list` / the Vertex console) when this
is actually built.

Both remain configurable via the existing `MODEL_REASONING`/`MODEL_FAST` settings — no new
"which model" concept needed, only a new "which gateway serves this model" concept.

---

## 6. Effort estimate (Option A — recommended)

| Item | Size | Estimate |
|---|---|---|
| `litellm_config.yaml` (model alias → `vertex_ai/gemini-*`/`vertex_ai/claude-*` mapping, virtual keys) | S | half a day |
| New `deploy_cloudrun-litellm-vertex-proxy.py` (CPU-only Cloud Run service, LiteLLM proxy image) | S | half a day — simpler than the existing GPU deploy scripts |
| IAM: proxy service account gets `roles/aiplatform.user` | XS | 1 hour |
| `deploy_cloudrun-micro-cosmos-app.py` + `deploy.py`: conditional Vertex engine branch, model-ID-alignment safeguard | S | half a day |
| `Settings`/`build_llm()`/`driver.py` changes | XS | likely none, or trivial — confirm during implementation |
| **Tool-calling verification for both Gemini-via-Vertex and Claude-via-Vertex** against real ADK `FunctionTool` agents, through the proxy | M | 1 day — biggest risk in this plan, needs a real GCP project with both models enabled |
| End-to-end live verification (real pipeline run against Vertex, both a Gemini-backed and a Claude-backed configuration) | M | 1 day |
| Docs: `CLAUDE.md`, `README.md` (correct the currently-aspirational Vertex section), `deployment/README.md`, a new `transferable-skills/memory/*.md` entry | S | half a day |

**Total engineering estimate: ~3.5–4 days** (roughly half a day less than revision 1's Option-B-only
estimate, mainly because `build_llm()`/`driver.py` need little-to-no change under Option A).

**Not an engineering estimate, but a real external dependency**: Anthropic's Claude models on
Vertex AI Model Garden require the target GCP project/org to have that partner model **enabled and
allowlisted** — a GCP console/administrative step, sometimes with its own approval lead time,
outside engineering control. Confirm this exists (or request it) before scheduling the work above;
the tool-calling verification step can't start without it.

---

## 7. Recommended order of work

1. Confirm Claude-on-Vertex Model Garden access is enabled for the target GCP project (external
   dependency — start first, can gate everything else).
2. Stand up the LiteLLM Proxy locally first (not yet on Cloud Run) against real Vertex credentials,
   config only Gemini initially (lower access risk), confirm `micro-cosmos-web` can talk to it unchanged
   via `LLM_BASE_URL`/`LLM_API_KEY` pointed at the local proxy.
3. Add Claude to the same local proxy config once Model Garden access is confirmed.
4. Tool-calling verification against a real pipeline run through the proxy, Gemini first, then
   Claude.
5. Only once the app-level path is proven: build `deploy_cloudrun-litellm-vertex-proxy.py` and the
   `deploy.py`/`deploy_cloudrun-micro-cosmos-app.py` conditional wiring.
6. Docs + `transferable-skills/memory/` entry, following the LM Studio→vLLM engine-swap writeup's
   style.
7. Decide on the ASK tab question (§3) as a fast follow, not a blocker.
