"""In-app report browser: every HTML report, plus translated project files."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DATAFORM = "examples/bigquery_dataform_retail"


@pytest.fixture
def client(monkeypatch, tmp_path):
    import importlib

    from fastapi.testclient import TestClient

    import micro_cosmos.settings as settings_mod

    settings = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", settings)
    app_module = importlib.import_module("micro_cosmos.web.app")

    async def _noop_start(self):
        return None

    monkeypatch.setattr(app_module.Run, "start", _noop_start)
    test_client = TestClient(app_module.app)
    login = test_client.post("/login", data={
        "username": settings_mod.get_settings().demo_username,
        "password": settings_mod.get_settings().demo_password,
    })
    assert login.status_code in (200, 303)
    return test_client


def test_every_html_report_is_listed() -> None:
    from micro_cosmos.web.app import _FILE_TO_SCRIPT, _REPORT_LABELS

    assert set(_REPORT_LABELS) == set(_FILE_TO_SCRIPT)


def _start_run(client) -> str:
    created = client.post("/runs", data={
        "source_path": DATAFORM,
        "source_lang": "sqlx",
        "target_lang": "snowflake_dbt",
        "skip_llm": "true",
    })
    assert created.status_code == 200
    match = re.search(r"/runs/([0-9a-f]{8})", created.text)
    assert match, created.text
    return match.group(1)


def test_browse_opens_full_report_inside_the_app(client) -> None:
    run_id = _start_run(client)
    page = client.get(f"/runs/{run_id}")
    assert page.status_code == 200
    href = f"/runs/{run_id}/browse/full-app-migration-report.html"
    full_group = page.text.split("reports-menu-full-download", 1)[1].split("reports-menu-separator", 1)[0]
    assert "Browse reports" in full_group
    assert href in full_group
    assert 'target="_blank"' in full_group

    home = client.get(f"/runs/{run_id}/browse", follow_redirects=False)
    assert home.status_code == 302
    assert home.headers["location"].endswith(f"/runs/{run_id}/browse/full-app-migration-report.html")

    browser = client.get(href)
    assert browser.status_code == 200
    assert 'class="report-browser"' in browser.text
    assert f'src="/runs/{run_id}/files/full-app-migration-report.html"' in browser.text
    assert 'aria-current="page"' in browser.text
    for name in (
        "executive-summary.html",
        "migration-briefing.html",
        "project-synthesis.html",
        "hotspots.html",
        "dead-code.html",
        "architecture-decisions.html",
        "fitness-stubs.html",
        "monitoring.html",
        "security-report.html",
        "output-security-report.html",
        "ir-graph.html",
        "sprint-plan.html",
        "feature-specs.html",
    ):
        assert f"/runs/{run_id}/browse/{name}" in browser.text
    assert "Translated code" not in browser.text

    missing = client.get(f"/runs/{run_id}/browse/not-a-report.html")
    assert missing.status_code == 404
    assert client.get("/runs/does-not-exist/browse").status_code == 404

    from micro_cosmos.settings import get_settings

    report = Path(get_settings().runs_dir) / run_id / "reports" / "executive-summary.html"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("<html><body>Summary body</body></html>", encoding="utf-8")
    served = client.get(f"/runs/{run_id}/files/executive-summary.html")
    assert served.status_code == 200
    assert "inline" in served.headers["content-disposition"]
    assert "Summary body" in served.text


def test_browse_surfaces_translated_files(client) -> None:
    from micro_cosmos.settings import get_settings

    run_id = _start_run(client)
    project = Path(get_settings().runs_dir) / run_id / "reports" / "retail_snowflake"
    (project / "models").mkdir(parents=True)
    (project / "models" / "stg_orders.sql").write_text(
        "select 1 as id\n-- <script>alert(1)</script>\n",
        encoding="utf-8",
    )
    (project / "models" / "secret.bin").write_bytes(b"\x00\x01")
    (project / "dbt_project.yml").write_text("name: retail\n", encoding="utf-8")
    (project / "profiles.yml.example").write_text("example:\n", encoding="utf-8")

    page = client.get(f"/runs/{run_id}/browse/full-app-migration-report.html")
    assert page.status_code == 200
    assert "Translated code" in page.text
    assert "models/stg_orders.sql" in page.text
    assert "dbt_project.yml" in page.text
    assert "profiles.yml.example" in page.text
    assert "secret.bin" not in page.text

    shell = client.get(f"/runs/{run_id}/browse/code/models/stg_orders.sql")
    assert shell.status_code == 200
    assert f'src="/runs/{run_id}/translated/models/stg_orders.sql"' in shell.text
    assert 'aria-current="page"' in shell.text

    raw = client.get(f"/runs/{run_id}/translated/models/stg_orders.sql")
    assert raw.status_code == 200
    assert "select 1 as id" in raw.text
    assert "<script>alert(1)</script>" not in raw.text
    assert "&lt;script&gt;" in raw.text

    assert client.get(f"/runs/{run_id}/translated/models/secret.bin").status_code == 404
    assert client.get(f"/runs/{run_id}/translated/models/../../run_meta.json").status_code == 404
    assert client.get(f"/runs/{run_id}/browse/code/models/missing.sql").status_code == 404


def test_vector_index_is_not_translated_code(client) -> None:
    from micro_cosmos.settings import get_settings

    run_id = _start_run(client)
    run_dir = Path(get_settings().runs_dir) / run_id
    reports = run_dir / "reports"
    reports.mkdir(parents=True)
    (reports / "project_dir.txt").write_text("definitions_snowflakedbt\n", encoding="utf-8")
    vectors = run_dir / "source_vectors"
    vectors.mkdir()
    (vectors / "meta.json").write_text('{"chunks": 1}\n', encoding="utf-8")

    page = client.get(f"/runs/{run_id}/browse/full-app-migration-report.html")
    assert page.status_code == 200
    assert "Translated code" not in page.text
    assert "meta.json" not in page.text

    project = reports / "definitions_snowflakedbt" / "models"
    project.mkdir(parents=True)
    (project / "mart_daily.sql").write_text("select 1\n", encoding="utf-8")
    listed = client.get(f"/runs/{run_id}/browse/full-app-migration-report.html")
    assert "models/mart_daily.sql" in listed.text
    opened = client.get(f"/runs/{run_id}/translated/models/mart_daily.sql")
    assert opened.status_code == 200
    assert "select 1" in opened.text


def test_browse_lists_kiro_skills_and_openspec_before_translated_code(client) -> None:
    from micro_cosmos.settings import get_settings

    run_id = _start_run(client)
    reports = Path(get_settings().runs_dir) / run_id / "reports"

    kiro = reports / "kiro-dev-powers-app-modernization" / "micro-cosmos-code-writer-power"
    spec = kiro / ".kiro" / "specs" / "micro-cosmos-code-writer-power"
    spec.mkdir(parents=True)
    (kiro / "POWER.md").write_text("# writer\n", encoding="utf-8")
    (spec / "design.md").write_text("design body\n", encoding="utf-8")
    (spec / ".config.kiro").write_text("config body\n", encoding="utf-8")

    skills = reports / "retail_skills" / ".claude" / "commands"
    skills.mkdir(parents=True)
    (reports / "retail_skills" / "CLAUDE.md").write_text("# skills\n", encoding="utf-8")
    (skills / "code-review.md").write_text("review the seam\n<script>no</script>\n", encoding="utf-8")

    change = reports / "openspec" / "changes" / "sqlx-migration"
    change.mkdir(parents=True)
    (reports / "openspec" / "project.md").write_text("# project\n", encoding="utf-8")
    (change / "proposal.md").write_text("proposal body\n", encoding="utf-8")

    project = reports / "retail_snowflake" / "models"
    project.mkdir(parents=True)
    (project / "stg_orders.sql").write_text("select 1\n", encoding="utf-8")

    page = client.get(f"/runs/{run_id}/browse/full-app-migration-report.html")
    assert page.status_code == 200
    body = page.text
    kiro_at = body.index("Kiro.dev Powers")
    skills_at = body.index("Claude Code skills")
    spec_at = body.index("OpenSpec")
    code_at = body.index("Translated code")
    assert kiro_at < skills_at < spec_at < code_at
    assert "POWER.md" in body
    assert "micro-cosmos-code-writer-power/.kiro/specs/micro-cosmos-code-writer-power/design.md" in body
    assert "micro-cosmos-code-writer-power/.kiro/specs/micro-cosmos-code-writer-power/.config.kiro" in body
    assert ".claude/commands/code-review.md" in body
    assert "changes/sqlx-migration/proposal.md" in body
    assert "models/stg_orders.sql" in body

    shell = client.get(f"/runs/{run_id}/browse/pack/skills/.claude/commands/code-review.md")
    assert shell.status_code == 200
    assert 'aria-current="page"' in shell.text
    assert f'src="/runs/{run_id}/pack/skills/.claude/commands/code-review.md"' in shell.text
    raw = client.get(f"/runs/{run_id}/pack/skills/.claude/commands/code-review.md")
    assert raw.status_code == 200
    assert "review the seam" in raw.text
    assert "<script>no</script>" not in raw.text

    kiro_file = client.get(
        "/runs/" + run_id + "/pack/kiro/"
        "micro-cosmos-code-writer-power/.kiro/specs/micro-cosmos-code-writer-power/.config.kiro"
    )
    assert kiro_file.status_code == 200
    assert "config body" in kiro_file.text
    assert client.get(f"/runs/{run_id}/pack/openspec/changes/sqlx-migration/proposal.md").status_code == 200
    assert client.get(f"/runs/{run_id}/pack/nope/project.md").status_code == 404
    assert client.get(f"/runs/{run_id}/pack/skills/../../run_meta.json").status_code == 404
    assert client.get(f"/runs/{run_id}/browse/pack/kiro/missing.md").status_code == 404
