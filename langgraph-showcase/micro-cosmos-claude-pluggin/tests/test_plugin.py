"""Layout tests for the Micro-Cosmos Claude plugin."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run_artifacts import write_run_record

WEB = (
    "Spring Boot",
    "Axon Framework",
    "NestJS",
    "React",
    "Django",
    "Flask",
    "ASP.NET Core",
)
DATA = ("Databricks", "Azure Data Factory", "Dataform", "dbt")


def _words(text: str) -> int:
    stripped = re.sub(r"```.*?```", " ", text, flags=re.S)
    return len(re.findall(r"[A-Za-z0-9']+", stripped))


class LayoutTest(unittest.TestCase):
    def test_manifest_and_listing(self) -> None:
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "micro-cosmos")
        self.assertEqual(manifest["displayName"], "Micro-Cosmos")
        self.assertEqual(manifest["version"], "1.0.0")
        readme = (ROOT / "README.md").read_text()
        self.assertGreaterEqual(_words(readme), 40)
        self.assertIn("application framework translation", readme.lower())
        for name in WEB + DATA:
            self.assertIn(name, readme)
            self.assertIn(name, manifest["description"])

    def test_engine_is_the_low_level_pipeline(self) -> None:
        observer = (ROOT / "micro_cosmos" / "tools" / "observer_tools.py").read_text()
        cartographer = (ROOT / "micro_cosmos" / "tools" / "cartographer_tools.py").read_text()
        pipeline = (ROOT / "micro_cosmos" / "orchestration" / "pipeline.py").read_text()
        self.assertIn("tree_sitter", observer)
        self.assertIn("def analyse_bounded_contexts", cartographer)
        self.assertIn("skip_gate_validation", pipeline)
        self.assertFalse((ROOT / "micro_cosmos" / "web").exists())

    def test_commands_call_the_runner(self) -> None:
        plan = (ROOT / "commands" / "plan.md").read_text()
        translate = (ROOT / "commands" / "translate.md").read_text()
        self.assertIn("--depth plan", plan)
        self.assertIn("--depth translate", translate)
        self.assertIn("run_pipeline.py", plan)
        self.assertIn("run_pipeline.py", translate)
        for text in (plan, translate, (ROOT / "skills" / "micro-cosmos" / "SKILL.md").read_text()):
            self.assertNotIn(".env", text)

    def test_listing_icon(self) -> None:
        data = (ROOT / ".claude-plugin" / "icon.png").read_bytes()
        self.assertLess(len(data), 2 * 1024 * 1024)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        self.assertEqual(width, height)
        self.assertGreaterEqual(width, 512)
        self.assertLessEqual(width, 2048)

    def test_runner_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "run_pipeline.py"), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--mode", result.stdout)
        self.assertIn("deterministic", result.stdout)
        self.assertIn("plan", result.stdout)

    def test_commands_match_the_two_depths(self) -> None:
        plan = (ROOT / "commands" / "plan.md").read_text()
        translate = (ROOT / "commands" / "translate.md").read_text()
        self.assertIn("pause_after_planning", plan)
        self.assertIn("PLAN_COMPLETE.md", plan)
        self.assertIn("Code translation does not start", plan)
        self.assertIn("PR gate", translate)
        self.assertIn("reports/<project>_<target>/", translate)
        driver = (ROOT / "micro_cosmos" / "orchestration" / "driver.py").read_text()
        self.assertIn("stop_after_code_translation", driver)
        self.assertLess(
            driver.index("async for ev in _run_all_seams()"),
            driver.index("stop_after_code_translation"),
        )

    def test_plan_and_translate_artifacts(self) -> None:
        with self.subTest("plan"):
            run = ROOT / "tests" / "_tmp_plan"
            if run.exists():
                import shutil
                shutil.rmtree(run)
            run.mkdir()
            (run / "ir_graph.json").write_text(json.dumps({
                "nodes": [{"id": "a"}],
                "cqrs_framework_hints": {
                    "detected_frameworks": ["Spring Boot"],
                    "evidence": {"Spring Boot": "pom.xml"},
                },
            }))
            (run / "bounded_context_map.json").write_text(json.dumps({"contexts": []}))
            (run / "seam.json").write_text(json.dumps({
                "seams": [{"id": "orders", "substitution_note": "Move the controller."}],
            }))
            (run / "work_streams.json").write_text("{}")
            (run / "tnas.json").write_text(json.dumps({"target_lang": "kotlin", "services": []}))
            (run / "security_report.json").write_text(json.dumps({"findings": []}))
            (run / "feature_specs.json").write_text(json.dumps({
                "specs": [{"seam_id": "orders", "title": "Orders"}],
            }))
            record = write_run_record(
                run,
                source_path="/src/shop",
                source_lang="java",
                target_lang="kotlin",
                mode="deterministic",
                depth="plan",
                account_id="acct",
            )
            self.assertEqual(record["frameworks_detected"], ["Spring Boot"])
            self.assertEqual(record["depth"], "plan")
            complete = (run / "PLAN_COMPLETE.md").read_text()
            self.assertIn("Code translation did not start.", complete)
            self.assertIn("ir_graph.json", complete)
            plan_text = (run / "framework_translation_plan.md").read_text()
            self.assertIn("Spring Boot", plan_text)
            self.assertIn("Move the controller.", plan_text)
            import shutil
            shutil.rmtree(run)

        with self.subTest("translate"):
            import shutil
            run = ROOT / "tests" / "_tmp_translate"
            if run.exists():
                shutil.rmtree(run)
            run.mkdir()
            for name in (
                "ir_graph.json",
                "bounded_context_map.json",
                "seam.json",
                "work_streams.json",
                "tnas.json",
                "security_report.json",
                "feature_specs.json",
            ):
                (run / name).write_text("{}")
            (run / "ir_graph.json").write_text(json.dumps({"nodes": []}))
            (run / "bounded_context_map.json").write_text(json.dumps({"contexts": []}))
            (run / "security_report.json").write_text(json.dumps({"findings": []}))
            (run / "tnas.json").write_text(json.dumps({"target_lang": "go"}))
            tree = run / "reports" / "shop_go"
            tree.mkdir(parents=True)
            (tree / "main.go").write_text("package main\n")
            write_run_record(
                run,
                source_path="/src/shop",
                source_lang="java",
                target_lang="go",
                mode="llm",
                depth="translate",
                account_id="acct",
            )
            self.assertFalse((run / "PLAN_COMPLETE.md").exists())
            self.assertIn("No gaps recorded.", (run / "gaps.md").read_text())
            shutil.rmtree(run)

    def test_feature_specs_use_the_planner_document(self) -> None:
        import shutil
        run = ROOT / "tests" / "_tmp_specs"
        if run.exists():
            shutil.rmtree(run)
        run.mkdir()
        (run / "feature_specs_result.json").write_text(json.dumps({"specs": [{"seam_id": "main"}]}))
        for name in (
            "ir_graph.json",
            "bounded_context_map.json",
            "seam.json",
            "work_streams.json",
            "tnas.json",
            "security_report.json",
        ):
            (run / name).write_text("{}")
        (run / "ir_graph.json").write_text(json.dumps({"nodes": []}))
        (run / "bounded_context_map.json").write_text(json.dumps({"contexts": []}))
        (run / "tnas.json").write_text(json.dumps({"target_lang": "go"}))
        (run / "security_report.json").write_text(json.dumps({"findings": []}))
        write_run_record(
            run,
            source_path="/src/shop",
            source_lang="java",
            target_lang="go",
            mode="deterministic",
            depth="plan",
            account_id="acct",
            warnings=["security: Trivy scan warning: Trivy not found"],
        )
        specs = json.loads((run / "feature_specs.json").read_text())
        self.assertEqual(specs["specs"][0]["seam_id"], "main")
        self.assertIn("feature_specs.json", (run / "PLAN_COMPLETE.md").read_text())
        self.assertIn("were not scanned with Trivy", (run / "gaps.md").read_text())
        self.assertNotIn("curl", (run / "gaps.md").read_text())
        shutil.rmtree(run)

    def test_license_is_five_free_then_fifteen(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "micro_cosmos_entitlement",
            ROOT / "entitlement" / "entitlement.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.FREE_RUN_LIMIT, 5)
        self.assertEqual(module.MONTHLY_PRICE_USD, 15)
        self.assertIn("5 runs", module.PAYMENT_MESSAGE)
        self.assertIn("$15", module.PAYMENT_MESSAGE)
        for name in ("README.md", "PLAN.md", "commands/plan.md", "commands/translate.md", "entitlement/ENTITLEMENT.md"):
            text = (ROOT / name).read_text()
            self.assertIn("$15", text)
            self.assertNotIn("$10", text)
