"""Layout and entitlement tests for the Micro-Focus plugin."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WEB_FRAMEWORKS = (
    "Spring Boot",
    "Axon Framework",
    "NestJS",
    "React",
    "Django",
    "Flask",
    "ASP.NET Core",
)
DATA_FRAMEWORKS = (
    "Databricks",
    "Azure Data Factory",
    "Dataform",
    "dbt",
)
PHASES = (
    "Observer",
    "Cartographer",
    "Architect",
    "Security analysis",
    "Framework translation planner",
    "Code translation",
)


def _load_entitlement():
    path = ROOT / "entitlement" / "entitlement.py"
    spec = importlib.util.spec_from_file_location("micro_focus_entitlement", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _words_outside_code(text: str) -> int:
    stripped = re.sub(r"```.*?```", " ", text, flags=re.S)
    return len(re.findall(r"[A-Za-z0-9']+", stripped))


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        raise AssertionError("missing front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise AssertionError("front matter does not close")
    return text[4:end]


class PluginLayoutTest(unittest.TestCase):
    def test_manifest_names_application_framework_translation(self) -> None:
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "micro-focus")
        self.assertEqual(manifest["displayName"], "Micro-Focus")
        self.assertEqual(manifest["version"], "1.0.1")
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["author"]["name"], "Joao Pedro Afonso Cerqueira")
        description = manifest["description"]
        self.assertIn("Application framework translation", description)
        for name in WEB_FRAMEWORKS + ("BigQuery", "Snowflake"):
            self.assertIn(name, description)
        for name in DATA_FRAMEWORKS:
            self.assertIn(name, description)

    def test_readme_is_long_enough_and_lists_frameworks(self) -> None:
        readme = (ROOT / "README.md").read_text()
        self.assertGreaterEqual(_words_outside_code(readme), 40)
        self.assertIn("application framework translation", readme.lower())
        self.assertIn("Web frameworks", readme)
        self.assertIn("Data engineering frameworks", readme)
        for name in WEB_FRAMEWORKS + DATA_FRAMEWORKS:
            self.assertIn(name, readme)
        self.assertIn("$10", readme)
        self.assertIn("10", readme)
        self.assertIn("not sent to another service", readme)

    def test_license_matches_mit_grant(self) -> None:
        text = (ROOT / "LICENSE").read_text()
        self.assertIn("Copyright (c) 2026 Joao Pedro Afonso Cerqueira", text)
        self.assertIn("furnished to do so, subject to the following conditions:", text)

    def test_plan_records_plugin_only_submission_repo(self) -> None:
        plan = (ROOT / "PLAN.md").read_text()
        self.assertIn("new Git repository", plan)
        self.assertIn("plugin path is left empty", plan)
        self.assertIn("micro-cosmos repository is not the submission", plan)
        for name in WEB_FRAMEWORKS + DATA_FRAMEWORKS:
            self.assertIn(name, plan)

    def test_phase_mode_and_gate_docs(self) -> None:
        phases = (ROOT / "skills" / "micro-focus" / "references" / "phases.md").read_text()
        modes = (ROOT / "skills" / "micro-focus" / "references" / "modes.md").read_text()
        gates = (ROOT / "skills" / "micro-focus" / "references" / "no-gates.md").read_text()
        frameworks = (ROOT / "skills" / "micro-focus" / "references" / "frameworks.md").read_text()
        for phase in PHASES:
            self.assertIn(phase, phases)
        self.assertIn("PLAN_COMPLETE.md", phases)
        self.assertIn("did not start", phases.lower())
        self.assertNotIn(".env", phases)
        self.assertNotIn("secret", phases.lower())
        self.assertIn("deterministic", modes.lower())
        self.assertIn("llm", modes.lower())
        for gate in ("Gate 1", "Gate 2", "Gate 3", "Gate 4", "Gate 4.5", "Gate 5"):
            self.assertIn(gate, gates)
        self.assertIn("does not stop", gates.lower())
        for name in WEB_FRAMEWORKS + DATA_FRAMEWORKS:
            self.assertIn(name, frameworks)

    def test_commands_and_skill(self) -> None:
        skill = (ROOT / "skills" / "micro-focus" / "SKILL.md").read_text()
        plan = (ROOT / "commands" / "plan.md").read_text()
        translate = (ROOT / "commands" / "translate.md").read_text()
        self.assertIn("name: micro-focus", _frontmatter(skill))
        self.assertIn("description:", _frontmatter(skill))
        self.assertIn("description:", _frontmatter(plan))
        self.assertIn("description:", _frontmatter(translate))
        self.assertIn("stop before code translation", plan.lower())
        self.assertIn("code translation", translate.lower())
        for text in (skill, plan, translate):
            self.assertIn("entitlement/entitlement.py", text)
            self.assertIn("Spring Boot", text)
            self.assertIn("Databricks", text)
            self.assertNotIn("license/entitlement.py", text)

    def test_entitlement_doc_states_the_price(self) -> None:
        text = (ROOT / "entitlement" / "ENTITLEMENT.md").read_text()
        self.assertIn("10", text)
        self.assertIn("$10 a month", text)
        self.assertIn("~/.micro-focus/accounts/", text)

    def test_listing_icon_is_a_square_png(self) -> None:
        icon = ROOT / ".claude-plugin" / "icon.png"
        data = icon.read_bytes()
        self.assertLess(len(data), 2 * 1024 * 1024)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(data[12:16], b"IHDR")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        self.assertEqual(width, height)
        self.assertGreaterEqual(width, 512)
        self.assertLessEqual(width, 2048)

    def test_forbidden_plugin_entries_are_absent(self) -> None:
        self.assertFalse((ROOT / ".mcp.json").exists())
        self.assertFalse((ROOT / "bin").exists())
        self.assertFalse((ROOT / "hooks").exists())


class EntitlementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entitlement = _load_entitlement()

    def test_ten_free_runs_then_payment_required(self) -> None:
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        record = self.entitlement.empty_ledger("user@example.com")
        for expected_remaining in range(9, -1, -1):
            record, receipt = self.entitlement.consume(record, now)
            self.assertTrue(receipt["allowed"])
            self.assertEqual(receipt["reason"], "free")
            self.assertEqual(receipt["remaining_free"], expected_remaining)
        self.assertEqual(record["free_runs_used"], 10)
        with self.assertRaises(self.entitlement.EntitlementError) as raised:
            self.entitlement.consume(record, now)
        self.assertIn("$10 a month", str(raised.exception))
        blocked = self.entitlement.assess(record, now)
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["price_usd_per_month"], 10)

    def test_active_subscription_is_unlimited_and_does_not_spend_free_runs(self) -> None:
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        record = self.entitlement.empty_ledger("user@example.com")
        record["free_runs_used"] = 10
        record["subscription"] = {
            "status": "active",
            "renews_at": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        updated, receipt = self.entitlement.consume(record, now)
        self.assertTrue(receipt["allowed"])
        self.assertEqual(receipt["reason"], "subscription")
        self.assertEqual(updated["free_runs_used"], 10)

    def test_expired_subscription_blocks_after_free_runs(self) -> None:
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        record = self.entitlement.empty_ledger("user@example.com")
        record["free_runs_used"] = 10
        record["subscription"] = {
            "status": "active",
            "renews_at": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        decision = self.entitlement.assess(record, now)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "payment_required")

    def test_cli_consumes_a_ledger_and_then_refuses(self) -> None:
        script = ROOT / "entitlement" / "entitlement.py"
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "account.json"
            for _ in range(10):
                result = subprocess.run(
                    [sys.executable, str(script), "consume", "--ledger", str(ledger), "--account", "user@example.com"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(json.loads(result.stdout)["allowed"])
            refused = subprocess.run(
                [sys.executable, str(script), "consume", "--ledger", str(ledger), "--account", "user@example.com"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(refused.returncode, 2)
            payload = json.loads(refused.stdout)
            self.assertFalse(payload["allowed"])
            self.assertIn("$10 a month", payload["message"])
            stored = json.loads(ledger.read_text())
            self.assertEqual(stored["free_runs_used"], 10)


if __name__ == "__main__":
    unittest.main()
