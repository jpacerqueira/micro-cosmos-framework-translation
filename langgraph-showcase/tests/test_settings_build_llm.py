"""Unit tests for Settings.build_llm()'s per-engine branching.

LiteLlm stores `model` as a direct attribute and everything else
(api_base, api_key, extra_body, vertex_project, vertex_location, ...) in
`._additional_args` — verified directly against the installed
google.adk.models.lite_llm.LiteLlm before writing these assertions.
"""

from __future__ import annotations

import micro_cosmos.settings as settings_mod


def test_build_llm_lmstudio_engine():
    s = settings_mod.Settings(
        llm_engine="lmstudio",
        model_reasoning="google/gemma-4-e4b",
        model_context_length=16384,
        llm_base_url="http://x/v1",
        llm_api_key="key",
    )
    llm = s.build_llm("reasoning")
    assert llm.model == "openai/google/gemma-4-e4b"
    assert llm._additional_args["api_base"] == "http://x/v1"
    assert llm._additional_args["api_key"] == "key"
    assert llm._additional_args["extra_body"] == {"num_ctx": 16384}


def test_build_llm_vllm_engine_omits_extra_body():
    # vLLM's OpenAI-compatible endpoint has strict schema validation and
    # rejects unrecognized top-level fields — sending num_ctx would break
    # every request (real incident, see micro_cosmos/settings.py's comment).
    s = settings_mod.Settings(
        llm_engine="vllm",
        model_reasoning="Qwen/Qwen3.6-35B-A3B-FP8",
        llm_base_url="http://x/v1",
        llm_api_key="key",
    )
    llm = s.build_llm("reasoning")
    assert llm.model == "openai/Qwen/Qwen3.6-35B-A3B-FP8"
    assert llm._additional_args["extra_body"] is None


def test_build_llm_vertex_engine_claude_model():
    s = settings_mod.Settings(
        llm_engine="vertex",
        model_reasoning="claude-sonnet-5",
        google_cloud_project="my-proj",
        google_cloud_location="europe-west4",
    )
    llm = s.build_llm("reasoning")
    assert llm.model == "vertex_ai/claude-sonnet-5"
    assert llm._additional_args["vertex_project"] == "my-proj"
    assert llm._additional_args["vertex_location"] == "europe-west4"
    assert "api_base" not in llm._additional_args
    assert "api_key" not in llm._additional_args
    assert "extra_body" not in llm._additional_args


def test_build_llm_vertex_engine_gemini_model():
    # Same vertex_ai/ branch handles both partner backends — the model-ID
    # prefix alone determines routing, not a second engine value.
    s = settings_mod.Settings(
        llm_engine="vertex",
        model_reasoning="gemini-3.0-pro",
        google_cloud_project="my-proj",
        google_cloud_location="us-central1",
    )
    llm = s.build_llm("reasoning")
    assert llm.model == "vertex_ai/gemini-3.0-pro"
    assert llm._additional_args["vertex_project"] == "my-proj"
    assert llm._additional_args["vertex_location"] == "us-central1"


def test_build_llm_vertex_engine_fast_role_uses_model_fast():
    s = settings_mod.Settings(
        llm_engine="vertex",
        model_reasoning="claude-sonnet-5",
        model_fast="claude-haiku-4-5-20251001",
        google_cloud_project="my-proj",
        google_cloud_location="us-central1",
    )
    llm = s.build_llm("fast")
    assert llm.model == "vertex_ai/claude-haiku-4-5-20251001"
