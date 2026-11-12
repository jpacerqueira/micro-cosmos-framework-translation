"""Write the same run-folder files the plan and translate commands expect.

The LangGraph pipeline already writes the analysis JSON. This module adds the
files those commands name on top of that output, using the JSON the pipeline
wrote for this run id.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ANALYSIS_FILES = (
    "ir_graph.json",
    "bounded_context_map.json",
    "seam.json",
    "work_streams.json",
    "tnas.json",
    "security_report.json",
    "feature_specs.json",
)


def project_dir_name(source_path: str, target_lang: str) -> str:
    base = Path(source_path).name.strip() if source_path else ""
    if not base:
        base = "project"
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", base).strip("_") or "project"
    lang = re.sub(r"[^a-z0-9]", "", target_lang.lower())
    return f"{slug}_{lang}" if lang else slug


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _frameworks(ir_graph: dict) -> list[str]:
    hints = ir_graph.get("cqrs_framework_hints") or {}
    if not isinstance(hints, dict):
        return []
    names = hints.get("detected_frameworks") or []
    return [str(name) for name in names] if isinstance(names, list) else []


def _evidence(ir_graph: dict) -> dict:
    hints = ir_graph.get("cqrs_framework_hints") or {}
    if not isinstance(hints, dict):
        return {}
    evidence = hints.get("evidence") or {}
    return evidence if isinstance(evidence, dict) else {}


def _promote_feature_specs(run_dir: Path) -> None:
    """The planner stores its document as feature_specs_result. The plan command names it feature_specs.json."""
    target = run_dir / "feature_specs.json"
    source = run_dir / "feature_specs_result.json"
    if target.is_file() or not source.is_file():
        return
    loaded = _load(source)
    if "specs" in loaded:
        target.write_text(json.dumps(loaded, indent=2) + "\n", encoding="utf-8")


def _gap_lines(warnings: list[str]) -> list[str]:
    lines: list[str] = []
    noted_trivy = False
    for line in warnings:
        if "Trivy" in line:
            if not noted_trivy:
                lines.append("Security analysis: dependency CVEs were not scanned with Trivy.")
                noted_trivy = True
            continue
        lines.append(line)
    return lines


def _gaps(run_dir: Path, depth: str, source_path: str, target_lang: str, warnings: list[str]) -> list[str]:
    lines = _gap_lines(warnings)
    ir_graph = _load(run_dir / "ir_graph.json")
    if not isinstance(ir_graph.get("nodes"), list):
        lines.append("Observer: ir_graph.nodes is not a list.")
    contexts = _load(run_dir / "bounded_context_map.json").get("contexts")
    if not isinstance(contexts, list):
        lines.append("Cartographer: contexts is missing.")
    tnas = _load(run_dir / "tnas.json")
    if "services" not in tnas and "target_lang" not in tnas:
        lines.append("Architect: tnas has neither services nor target_lang.")
    findings = _load(run_dir / "security_report.json").get("findings")
    if not isinstance(findings, list):
        lines.append("Security analysis: findings is not a list.")
    seams = _load(run_dir / "seam.json").get("seams")
    specs = _load(run_dir / "feature_specs.json").get("specs")
    if isinstance(seams, list) and seams and not specs:
        lines.append("Framework translation planner: feature specs are empty.")
    for name in ANALYSIS_FILES:
        if not (run_dir / name).is_file():
            lines.append(f"Missing artifact: {name}.")
    if depth == "translate":
        tree = run_dir / "reports" / project_dir_name(source_path, target_lang)
        if not tree.is_dir():
            lines.append("Code translation: the translated tree was not written.")
    return lines


def _framework_plan(
    run_dir: Path,
    source_lang: str,
    target_lang: str,
) -> str:
    ir_graph = _load(run_dir / "ir_graph.json")
    names = _frameworks(ir_graph)
    evidence = _evidence(ir_graph)
    seams = _load(run_dir / "seam.json").get("seams") or []
    specs = _load(run_dir / "feature_specs.json").get("specs") or []
    lines = [
        "# Framework translation plan",
        "",
        f"Source language: {source_lang}",
        f"Target: {target_lang}",
        "",
        "## Detected frameworks",
        "",
    ]
    if not names:
        lines.append("The source matched none of the listed frameworks. The run continues as a language translation.")
    else:
        for name in names:
            lines.append(
                f"- {name}. Evidence: {evidence.get(name, 'recorded on the IR graph')}. "
                f"Target: {target_lang}. The target replaces this framework unless the target language keeps it."
            )
    lines.extend(["", "## Seams", ""])
    if not isinstance(seams, list) or not seams:
        lines.append("No seams were recorded.")
    else:
        by_id = {}
        if isinstance(specs, list):
            for spec in specs:
                if isinstance(spec, dict) and spec.get("seam_id"):
                    by_id[spec["seam_id"]] = spec
        for seam in seams:
            if not isinstance(seam, dict):
                continue
            seam_id = seam.get("id", "")
            spec = by_id.get(seam_id, {})
            title = spec.get("title") or str(seam_id).replace("_", " ")
            note = seam.get("substitution_note") or spec.get("technical_notes") or ""
            lines.append(f"- {seam_id}: {title}. {note}".rstrip())
    lines.append("")
    return "\n".join(lines)


def write_run_record(
    run_dir: Path,
    *,
    source_path: str,
    source_lang: str,
    target_lang: str,
    mode: str,
    depth: str,
    account_id: str,
    warnings: list[str] | None = None,
) -> dict:
    """Write run.json, the framework plan, gaps.md, and PLAN_COMPLETE.md when depth is plan."""
    run_dir.mkdir(parents=True, exist_ok=True)
    _promote_feature_specs(run_dir)
    ir_graph = _load(run_dir / "ir_graph.json")
    record = {
        "source_path": source_path,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "mode": mode,
        "depth": depth,
        "account_id": account_id,
        "frameworks_detected": _frameworks(ir_graph),
    }
    (run_dir / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (run_dir / "framework_translation_plan.md").write_text(
        _framework_plan(run_dir, source_lang, target_lang),
        encoding="utf-8",
    )
    gap_lines = _gaps(run_dir, depth, source_path, target_lang, warnings or [])
    gap_text = "\n".join(f"- {line}" for line in gap_lines) if gap_lines else "No gaps recorded.\n"
    if gap_lines:
        gap_text += "\n"
    (run_dir / "gaps.md").write_text(gap_text, encoding="utf-8")

    if depth == "plan":
        names = ["run.json", *ANALYSIS_FILES, "framework_translation_plan.md", "gaps.md", "PLAN_COMPLETE.md"]
        present = [name for name in names if name == "PLAN_COMPLETE.md" or (run_dir / name).is_file()]
        body = "\n".join(f"- {name}" for name in present)
        (run_dir / "PLAN_COMPLETE.md").write_text(
            body + "\n\nCode translation did not start.\n",
            encoding="utf-8",
        )
    return record
