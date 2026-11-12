"""Runtime settings — local Ollama (OpenAI-compatible), LM Studio/vLLM, or Vertex AI inference via LiteLLM."""

from __future__ import annotations

import logging

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Floor for llm_ready_timeout_seconds — see the field's own docstring
# and the validator below for why 1500s (25 min, matching the existing
# default exactly — this value has always been the working assumption for
# this deploy, so it doubles as the floor too, not just a lower separate one).
_MIN_LLM_READY_TIMEOUT_SECONDS = 1500

# Child of the "micro_cosmos" logger (see micro_cosmos/__init__.py) — same handler,
# appears in `docker compose logs` / `gcloud run services logs read` with
# no extra setup.
log = logging.getLogger("micro_cosmos.settings")


class Settings(BaseSettings):
    """Configuration. Reads from environment + .env file.

    Local inference setup (Ollama — docker-compose baseline):
      1. Run Ollama on the host and `ollama pull gemma4:latest`.
      2. API default port 11434 (OpenAI-compat at /v1).
      3. Set MODEL_REASONING / MODEL_FAST to the Ollama tag (default gemma4:latest).

    Also supports LM Studio / vLLM via LLM_ENGINE. The server exposes an
    OpenAI-compatible API; Ollama needs no real API key but LiteLLM requires
    a non-empty string, so any value works.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI-compatible inference backend (Ollama default)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"  # any non-empty value is accepted

    # Which engine build_llm() targets — "gateway" (Compose LiteLLM proxy,
    # OpenAI /v1 to llm-gateway), "ollama" (host venv direct to Ollama),
    # "lmstudio", "vllm", or "vertex" (ADC on the app process). Compose
    # defaults to gateway; switch the *backend* with LLM_PROFILE on the
    # gateway container, not by changing this field.
    llm_engine: str = "ollama"
    # Active gateway profile name (ollama|lmstudio|bedrock|vertex|vllm).
    # Informational on the app; the gateway entrypoint is what loads YAML.
    llm_profile: str = "ollama"

    # Vertex AI routing — only read when llm_engine == "vertex". Auth flows
    # through Application Default Credentials (the Cloud Run service
    # account's IAM role, or `gcloud auth application-default login`
    # locally), not an API key. These field names match the
    # docker-compose.yml / README.md references that predate this field
    # existing — see product-roadmap-markup/Micro-Cosmos-with-LLMGateway-for-VertexAI-GCP.md.
    google_genai_use_vertexai: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"

    # Model identifier as served by the backend (Ollama tag / LM Studio id / etc.).
    # Both roles default to the same model; set MODEL_FAST to a smaller
    # variant in .env if you want faster responses for the Observer phase.
    model_reasoning: str = "gemma4:latest"
    model_fast: str = "gemma4:latest"

    # KV-cache context window sent to LM Studio as num_ctx per-request.
    # LM Studio may also need the context length set at model-load time in
    # its UI (Model → Advanced → Context Length) — per-request num_ctx alone
    # may be silently ignored by some LM Studio versions.
    # Set MODEL_CONTEXT_LENGTH in .env. 8192 is a safe minimum; 16384+ for
    # large source estates.
    model_context_length: int = 16384

    # Sampling temperature. None (default) omits the parameter so the model
    # uses its own built-in default.
    model_temperature: float | None = None

    # Before a fresh pipeline run's first LLM call, micro_cosmos/orchestration/driver.py
    # polls LM Studio's native REST API (GET {host}/api/v0/models — reports
    # each model's "state": "loaded"/"not-loaded") and waits up to this many
    # seconds for MODEL_REASONING/MODEL_FAST to actually be loaded, so a
    # cold-starting/still-downloading micro-cosmos-llmgateway instance doesn't get
    # hit with real traffic before it's ready. 1500s (25 min) comfortably
    # covers cold GPU provisioning + a clean ~22GB model download + lms load
    # — best-effort only: on timeout the run proceeds anyway rather than
    # blocking indefinitely, and a genuine failure surfaces from the real
    # LLM call instead.
    #
    # Floored at _MIN_LLM_READY_TIMEOUT_SECONDS (1500s / 25 min — same
    # as the default) by the validator below, added 2026-07-13: a real
    # Cloud Run cold start (fresh instance provisioning + GCS FUSE mount +
    # vLLM engine init + 34.89GiB shard load) measured at ~11-12 minutes for
    # an already-built image, and a genuinely fresh CreateService (full
    # image pull) measured 16m38s just to bind the port, before model
    # loading even starts — so this value must never be configurable below
    # 1500s, full stop, not just below some smaller "reasonable minimum."
    llm_ready_timeout_seconds: int = 1500

    @field_validator("llm_ready_timeout_seconds")
    @classmethod
    def _enforce_llm_ready_timeout_floor(cls, v: int) -> int:
        if v < _MIN_LLM_READY_TIMEOUT_SECONDS:
            log.warning(
                "LLM_READY_TIMEOUT_SECONDS=%s is below the %ss (25 min) floor — "
                "clamping up. A real Cloud Run cold start (instance provisioning + "
                "GCS FUSE mount + model load) has been measured taking up to ~25-29 "
                "minutes for a genuinely fresh deploy; a shorter wait risks sending "
                "real traffic to a still-loading backend.",
                v, _MIN_LLM_READY_TIMEOUT_SECONDS,
            )
            return _MIN_LLM_READY_TIMEOUT_SECONDS
        return v

    # When True every agent phase bypasses the LLM and calls the deterministic
    # tool directly. Useful when the local model is slow or unreliable. Also
    # governs the ASK tab (extractive-only answers) and embeddings (disabled,
    # falls back to lexical search) — this is a whole-app default, not just
    # the new-run form's toggle, which reads this same value for its
    # pre-checked state. Defaults to True (safe/fast out of the box); set
    # SKIP_LLM=false in .env or the environment for real LLM calls
    # everywhere, or just flip the per-run toggle for a single translation.
    skip_llm: bool = True

    # Cap on Code Writer → Skeptical/Test/Functional review retries per seam
    # (micro_cosmos/orchestration/driver.py's _run_tdd_loop_for_seam) before the
    # seam is marked "failed" and the pipeline moves on to the next seam —
    # the Writer phase still runs and packages the best-effort translation.
    # Every seam that ends the main pass "failed" gets exactly one further
    # focused retry attempt after all seams have been processed once (not
    # governed by this setting — that retry is always exactly 1 attempt).
    max_tdd_iterations_per_seam: int = 3

    @field_validator("max_tdd_iterations_per_seam")
    @classmethod
    def _enforce_min_tdd_iterations(cls, v: int) -> int:
        if v < 1:
            log.warning(
                "MAX_TDD_ITERATIONS_PER_SEAM=%s is below 1 — clamping to 1.", v
            )
            return 1
        return v

    # Artifact persistence — each run writes JSON files under this directory
    runs_dir: str = "runs"

    # Web UI
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    # Gate approval/rejection auth. When set, the X-Gate-Token header must
    # match this value on POST /runs/{id}/gates/{id}/approve|reject.
    # Leave empty (default) to disable auth — suitable for localhost-only use.
    gate_token: str = ""

    # Web UI login gate (session-cookie based, not real user management —
    # a single shared demo/demobxyz credential pair, same class of gate as
    # gate_token above).
    demo_username: str = "demo"
    demo_password: str = "demobxyz"
    # Signs the session cookie (via itsdangerous). Must be the SAME value
    # across every Cloud Run instance of a revision, or a cookie signed by
    # one instance won't validate on another — deploy_cloudrun-micro-cosmos-app.py
    # always sets this explicitly for that reason. Left empty (default), a
    # random key is generated once per process — fine for local
    # docker-compose (single container), since sessions just reset if the
    # container restarts.
    session_secret_key: str = ""
    # Marks the session cookie Secure (HTTPS-only transmission). Must be
    # True once the app is reachable over real HTTPS (e.g. behind the Cloud
    # Run Load Balancer) — browsers silently refuse to send a Secure cookie
    # over plain HTTP, so this stays False for local docker-compose.
    session_https_only: bool = False

    # LLM request timeout in seconds. Local models can be slow; increase if
    # observer agents time out on large runs.
    llm_timeout: int = 3600

    # Retrieval / ASK tab
    retrieval_top_k: int = 8
    embedding_model: str = ""
    embedding_base_url: str = ""

    # Anthropic API key — when set, routes claude-* model IDs to Anthropic directly
    # instead of through the local OpenAI-compatible backend.
    anthropic_api_key: str = ""

    def uses_llm_gateway(self) -> bool:
        """True when Compose (or env) routes OpenAI /v1 through llm-gateway."""
        engine = (self.llm_engine or "").lower()
        base = (self.llm_base_url or "").lower()
        return engine == "gateway" or "llm-gateway" in base

    def build_llm(self, role: str = "reasoning"):
        """Return a LiteLlm instance that calls the configured inference
        backend — Ollama, LM Studio, vLLM, Vertex AI, or the Compose gateway.

        Uses the openai provider (lmstudio/vllm/gateway/ollama) or vertex_ai
        provider (vertex) so LiteLLM serialises tool calls in the format each
        engine understands. drop_params=True silently drops parameters the
        engine doesn't support (logprobs, n, etc.) — but does NOT strip
        extra_body contents, which is why extra_body itself is conditional
        below.
        """
        from micro_cosmos.langgraph_runtime import GatewayModel as LiteLlm

        model_name = self.model_reasoning if role == "reasoning" else self.model_fast

        if self.llm_engine == "vertex":
            # Vertex is a fully managed endpoint — auth is ADC/IAM, not an
            # api_base/api_key pair, and extra_body's num_ctx is an LM
            # Studio/llama.cpp KV-cache parameter with no Vertex equivalent.
            # The vertex_ai/ prefix plus model_name is what routes LiteLLM
            # to the right partner backend — one branch handles both
            # Gemini and Claude model IDs.
            log.info(
                "build_llm(role=%s): engine=vertex model=%s project=%s location=%s "
                "temperature=%s",
                role, model_name, self.google_cloud_project,
                self.google_cloud_location, self.model_temperature,
            )
            return LiteLlm(
                model=f"vertex_ai/{model_name}",
                vertex_project=self.google_cloud_project,
                vertex_location=self.google_cloud_location,
                drop_params=True,
                timeout=self.llm_timeout,
                temperature=self.model_temperature,
            )

        extra_body = None
        if self.llm_engine == "lmstudio":
            # Tell LM Studio / llama.cpp to allocate a larger KV-cache window.
            # Without this the default is 4096 tokens, which is too small to
            # hold the system instruction + tool schemas + source file content.
            # vLLM has no such per-request parameter (context length is fixed
            # at server launch via --max-model-len) and its OpenAI endpoint
            # has strict schema validation that rejects unrecognized
            # top-level fields — sending num_ctx there would fail every
            # request. The Compose llm-gateway lmstudio profile injects
            # num_ctx itself, so gateway mode also omits extra_body.
            extra_body = {"num_ctx": self.model_context_length}
        log.info(
            "build_llm(role=%s): engine=%s profile=%s model=%s api_base=%s api_key_configured=%s "
            "temperature=%s extra_body=%s",
            role, self.llm_engine, self.llm_profile, model_name, self.llm_base_url,
            bool(self.llm_api_key), self.model_temperature, extra_body,
        )
        return LiteLlm(
            model=f"openai/{model_name}",
            api_base=self.llm_base_url,
            api_key=self.llm_api_key,
            drop_params=True,
            extra_body=extra_body,
            timeout=self.llm_timeout,
            temperature=self.model_temperature,
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
