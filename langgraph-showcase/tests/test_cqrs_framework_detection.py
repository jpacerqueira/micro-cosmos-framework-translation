"""Tests for micro_cosmos.tools.framework_tools.detect_cqrs_frameworks — deterministic
detection of known CQRS/event-sourcing frameworks (Axon, Eventuate, Lagom, MediatR,
NServiceBus, Wolverine) already in use in a source codebase, via dependency-manifest
coordinates and (Axon only) source annotations already on the IR graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from micro_cosmos.tools.framework_tools import detect_cqrs_frameworks

_EMPTY_IR: dict = {"nodes": []}


@pytest.mark.parametrize(
    ("manifest_name", "content", "expected"),
    [
        ("pom.xml", "<dependency><groupId>org.axonframework</groupId></dependency>", "AxonFramework"),
        ("pom.xml", "<dependency><groupId>io.eventuate.tram.core</groupId></dependency>", "Eventuate"),
        ("build.gradle", "implementation 'com.lightbend.lagom:lagom-javadsl-api_2.13'", "Lagom"),
        ("app.csproj", '<PackageReference Include="MediatR" Version="12.0.0" />', "MediatR"),
        ("app.csproj", '<PackageReference Include="NServiceBus.Core" Version="8.0.0" />', "NServiceBus"),
        ("app.csproj", '<PackageReference Include="WolverineFx" Version="1.0.0" />', "Wolverine"),
    ],
)
def test_manifest_signature_detects_framework(tmp_path: Path, manifest_name, content, expected) -> None:
    (tmp_path / manifest_name).write_text(content, encoding="utf-8")
    result = detect_cqrs_frameworks(str(tmp_path), _EMPTY_IR)
    assert expected in result["detected_frameworks"]


def test_no_matching_manifest_or_ir_signal_detects_nothing(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text(
        "<dependency><groupId>org.springframework</groupId></dependency>", encoding="utf-8"
    )
    result = detect_cqrs_frameworks(str(tmp_path), _EMPTY_IR)
    assert result["detected_frameworks"] == []


def test_axon_ir_node_fallback_fires_without_a_readable_manifest(tmp_path: Path) -> None:
    """Even with no manifest at all, an is_axon_aggregate node already on the IR graph
    (set by _parse_java_file's import-verified annotation detection) is enough."""
    ir = {
        "nodes": [
            {"id": "class.Portfolio", "attributes": {"is_axon_aggregate": "true"}},
        ]
    }
    result = detect_cqrs_frameworks(str(tmp_path), ir)
    assert "AxonFramework" in result["detected_frameworks"]
    assert "@Aggregate" in result["evidence"]["AxonFramework"]


async def test_cqrs_hints_written_in_deterministic_mode(monkeypatch, tmp_path) -> None:
    """BUG-2: run_phase()'s skip_llm branch returns before the post-phase hooks, so the
    post-OBSERVER CQRS hook never ran in Deterministic mode and cqrs_framework_hints was
    absent from ir_graph.json for every deterministic run — verified on run d92e257b.
    Same gap class as the deterministic-mode Trivy prescan fixed earlier.
    """
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator, PipelinePhase

    orch = MicroCosmosOrchestrator(run_id="cqrs-hint-run")
    await orch.initialise_session("examples/java-axonframework-example-app", "java", "kotlin")
    async for _ in orch.run_phase(PipelinePhase.OBSERVER):
        pass

    ir = orch.load_artifact("ir_graph")
    assert isinstance(ir, dict)
    assert "cqrs_framework_hints" in ir, (
        "cqrs_framework_hints must be written in Deterministic mode too"
    )
    assert "AxonFramework" in ir["cqrs_framework_hints"]["detected_frameworks"]
