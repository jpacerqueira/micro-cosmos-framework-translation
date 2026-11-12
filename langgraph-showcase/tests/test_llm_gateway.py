"""Compose llm-gateway is an OpenAI /v1 hop; backends switch via LLM_PROFILE."""

import os
from pathlib import Path

from micro_cosmos.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_build_llm_gateway_omits_extra_body():
    s = Settings(
        llm_engine="gateway",
        llm_profile="ollama",
        model_reasoning="gemma4:latest",
        llm_base_url="http://llm-gateway:4000/v1",
        llm_api_key="sk-micro-cosmos-local",
        model_context_length=131072,
    )
    llm = s.build_llm("reasoning")
    assert llm.model == "openai/gemma4:latest"
    assert llm._additional_args["api_base"] == "http://llm-gateway:4000/v1"
    assert llm._additional_args["api_key"] == "sk-micro-cosmos-local"
    assert llm._additional_args["extra_body"] is None


def test_uses_llm_gateway():
    assert Settings(
        llm_engine="gateway", llm_base_url="http://llm-gateway:4000/v1"
    ).uses_llm_gateway()
    assert Settings(
        llm_engine="ollama", llm_base_url="http://llm-gateway:4000/v1"
    ).uses_llm_gateway()
    assert not Settings(
        llm_engine="ollama", llm_base_url="http://localhost:11434/v1"
    ).uses_llm_gateway()
    assert not Settings(
        llm_engine="vertex", llm_base_url=""
    ).uses_llm_gateway()


def test_host_venv_defaults_are_direct_ollama(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("LLM_", "MODEL_")):
            monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.llm_engine == "ollama"
    assert s.llm_profile == "ollama"
    assert s.llm_base_url == "http://localhost:11434/v1"
    assert not s.uses_llm_gateway()


def test_compose_routes_app_through_llm_gateway():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "llm-gateway:" in compose
    assert "http://llm-gateway:4000/v1" in compose
    assert "LLM_PROFILE: ${LLM_PROFILE:-ollama}" in compose
    assert "LLM_ENGINE: ${LLM_ENGINE:-gateway}" in compose
    assert "ghcr.io/berriai/litellm:main-stable" in compose
    assert "GATEWAY_LOG_DIR" in compose
    assert '"4001:4000"' in compose
    profiles = {p.name for p in (ROOT / "llm-gateway" / "profiles").glob("*.yaml")}
    assert profiles == {
        "ollama.yaml",
        "lmstudio.yaml",
        "bedrock.yaml",
        "vertex.yaml",
        "vllm.yaml",
    }
    ollama = (ROOT / "llm-gateway" / "profiles" / "ollama.yaml").read_text()
    assert "gemma4:latest" in ollama
    assert "OLLAMA_API_BASE" in ollama
    assert "keep_alive" in ollama
    assert "custom_callbacks.proxy_handler_instance" in ollama
    for name in ("lmstudio.yaml", "bedrock.yaml", "vertex.yaml", "vllm.yaml"):
        text = (ROOT / "llm-gateway" / "profiles" / name).read_text()
        assert "custom_callbacks.proxy_handler_instance" in text
        assert "json_logs: true" in text
        assert "28800" in text
    entry = (ROOT / "llm-gateway" / "entrypoint.sh").read_text()
    assert "ollama|lmstudio|bedrock|vertex|vllm" in entry
    assert "no failover" in entry
    assert "--detailed_debug" in entry
    callback = (ROOT / "llm-gateway" / "profiles" / "custom_callbacks.py").read_text()
    assert "duration_ms" in callback
    assert "proxy_handler_instance" in callback


async def test_wait_for_llm_ready_skips_native_on_gateway(monkeypatch):
    from micro_cosmos.orchestration import driver

    calls: list[str] = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": []}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            calls.append(url)
            return _Resp()

    monkeypatch.setattr(driver.httpx, "AsyncClient", _Client)
    ready, msg = await driver._wait_for_llm_ready(
        "http://llm-gateway:4000/v1",
        {"gemma4:latest"},
        timeout_seconds=1500,
        api_key="sk-micro-cosmos-local",
        skip_native=True,
        poll_interval=0.01,
    )
    assert ready
    assert calls == ["http://llm-gateway:4000/v1/models"]
    assert "api/v0/models" not in "".join(calls)
