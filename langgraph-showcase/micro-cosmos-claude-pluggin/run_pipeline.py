"""Run the Micro-Cosmos LangGraph pipeline on a source folder.

Plan depth is pause_after_planning: Observer through the framework translation
planner, then stop. Translate depth runs that prefix and the seam loop, then
stops when the translated tree exists. It does not open the PR gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_artifacts import project_dir_name, write_run_record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Micro-Cosmos pipeline.")
    parser.add_argument("--source", required=True, help="Source folder")
    parser.add_argument("--target", required=True, help="Target language or data platform")
    parser.add_argument("--source-lang", default="", help="Source language; detected when omitted")
    parser.add_argument("--mode", required=True, choices=("deterministic", "llm"))
    parser.add_argument("--depth", required=True, choices=("plan", "translate"))
    parser.add_argument("--account", default="", help="Account id the user supplied for this run")
    parser.add_argument("--llm-base-url", default="", help="Model URL the user typed for this run")
    parser.add_argument("--llm-api-key", default="", help="Model key the user typed for this run")
    return parser


def _prepare_environment(runs: Path, args: argparse.Namespace) -> None:
    os.environ["RUNS_DIR"] = str(runs)
    os.environ["SKIP_LLM"] = "true" if args.mode == "deterministic" else "false"
    if args.llm_base_url:
        os.environ["LLM_BASE_URL"] = args.llm_base_url
    if args.llm_api_key:
        os.environ["LLM_API_KEY"] = args.llm_api_key


def _run_id(runs: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = stamp
    suffix = 2
    while (runs / candidate).exists():
        candidate = f"{stamp}-{suffix}"
        suffix += 1
    return candidate


async def _run(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve()
    if not source.is_dir():
        print(json.dumps({"ok": False, "message": "Source folder was not found."}))
        return 2
    runs = source / ".micro-cosmos"
    runs.mkdir(parents=True, exist_ok=True)
    _prepare_environment(runs, args)

    import micro_cosmos.settings as settings_mod

    settings_mod._settings = None
    from micro_cosmos.orchestration.driver import run_full_pipeline
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    from micro_cosmos.tools.observer_tools import detect_source_lang

    source_lang = args.source_lang or detect_source_lang(str(source))
    if not source_lang:
        print(json.dumps({"ok": False, "message": "Source language was not detected. Pass --source-lang."}))
        return 2

    run_id = _run_id(runs)
    plan = args.depth == "plan"
    orchestrator = MicroCosmosOrchestrator(
        run_id,
        skip_llm=args.mode == "deterministic",
        auto_approve_gates=True,
        auto_approve_reviewer_name="micro-cosmos-plugin",
        pause_after_planning=plan,
        skip_gate_validation=True,
        stop_after_code_translation=not plan,
    )
    warnings: list[str] = []
    async for event in run_full_pipeline(orchestrator, str(source), source_lang, args.target):
        print(event.to_json(), flush=True)
        if event.kind in {"warning", "error"}:
            message = ""
            if isinstance(event.payload, dict):
                message = str(event.payload.get("message") or event.payload.get("reason") or "")
            if message:
                warnings.append(f"{event.phase.value}: {message}")

    record = write_run_record(
        orchestrator.run_dir,
        source_path=str(source),
        source_lang=source_lang,
        target_lang=args.target,
        mode=args.mode,
        depth=args.depth,
        account_id=args.account,
        warnings=warnings,
    )
    tree = orchestrator.run_dir / "reports" / project_dir_name(str(source), args.target)
    summary = {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(orchestrator.run_dir),
        "mode": args.mode,
        "depth": args.depth,
        "source_lang": source_lang,
        "target_lang": args.target,
        "frameworks_detected": record["frameworks_detected"],
        "paused_after_planning": plan,
        "stopped_after_code_translation": not plan,
        "translated_tree": str(tree) if tree.is_dir() else "",
    }
    (orchestrator.run_dir / "plugin_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
