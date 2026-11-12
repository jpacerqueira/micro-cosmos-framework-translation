"""Tests for starting a demo run from a GitHub URL (download-as-zip).

`github_url` follows the same per-run, persisted-at-creation pattern as
`auto_approve_gates` (see test_auto_approve_gates.py and CLAUDE.md's
"Auto-approve gates" section) — it's purely descriptive metadata threaded
through `Run.__init__` / `create_run()` / `_restore_run()`, never consumed by
the pipeline itself.

`/demo/fetch-github` is validated in two tiers: URL/host validation happens
before any network call and is testable with no mocking (this is also where
the SSRF guard lives — only github.com URLs are ever turned into an outbound
request). The download path is exercised against a mocked
`urllib.request.urlopen` rather than a real GitHub call, mirroring how the
rest of this test suite avoids live network/LLM dependencies.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest


ESTATE = "examples/legacy_estate"


@pytest.fixture
def client(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    from fastapi.testclient import TestClient
    # NOT `import micro_cosmos.web.app as app_module` — see test_auto_approve_gates.py
    # for why the shadowed `app` attribute on the `micro_cosmos.web` package makes
    # importlib.import_module() the only safe way to get the module itself.
    app_module = importlib.import_module("micro_cosmos.web.app")

    async def _noop_start(self):
        return None

    monkeypatch.setattr(app_module.Run, "start", _noop_start)

    c = TestClient(app_module.app)
    resp = c.post("/login", data={
        "username": settings_mod.get_settings().demo_username,
        "password": settings_mod.get_settings().demo_password,
    })
    assert resp.status_code in (200, 303)
    return c, app_module, tmp_path


# ── POST /runs persistence ───────────────────────────────────────────────────

def test_post_runs_success_persists_github_url(client):
    c, _app_module, tmp_path = client
    resp = c.post("/runs", data={
        "source_path": ESTATE,
        "source_lang": "cobol",
        "target_lang": "go",
        "skip_llm": "true",
        "github_url": "https://github.com/octocat/Hello-World",
    })
    assert resp.status_code == 200

    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1
    meta = json.loads((run_dirs[0] / "run_meta.json").read_text())
    assert meta["github_url"] == "https://github.com/octocat/Hello-World"


def test_post_runs_defaults_github_url_to_empty(client):
    c, _app_module, tmp_path = client
    resp = c.post("/runs", data={
        "source_path": ESTATE,
        "source_lang": "cobol",
        "target_lang": "go",
        "skip_llm": "true",
    })
    assert resp.status_code == 200
    run_dirs = list(tmp_path.iterdir())
    meta = json.loads((run_dirs[0] / "run_meta.json").read_text())
    assert meta["github_url"] == ""


# ── _restore_run() round-trip ────────────────────────────────────────────────

def test_restore_run_round_trips_github_url(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")

    run_id = "restore-github-test"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_meta.json").write_text(json.dumps({
        "source_path": ESTATE, "source_lang": "cobol", "target_lang": "go",
        "skip_llm": True,
        "github_url": "https://github.com/octocat/Hello-World",
    }))

    app_module.RUNS.pop(run_id, None)
    run = app_module._restore_run(run_id)
    assert run is not None
    assert run.github_url == "https://github.com/octocat/Hello-World"


def test_restore_run_defaults_github_url_when_absent(monkeypatch, tmp_path):
    """run_meta.json written before this feature existed has no `github_url` key."""
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")

    run_id = "restore-legacy-test"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_meta.json").write_text(json.dumps({
        "source_path": ESTATE, "source_lang": "cobol", "target_lang": "go",
        "skip_llm": True,
    }))

    app_module.RUNS.pop(run_id, None)
    run = app_module._restore_run(run_id)
    assert run is not None
    assert run.github_url == ""


# ── POST /demo/fetch-github — URL/host validation (no network, SSRF guard) ──

def test_fetch_github_rejects_non_github_host(client):
    c, _app_module, _tmp_path = client
    resp = c.post("/demo/fetch-github", data={"github_url": "https://evil.com/owner/repo"})
    assert resp.status_code == 400


def test_fetch_github_rejects_non_https_scheme(client):
    c, _app_module, _tmp_path = client
    resp = c.post("/demo/fetch-github", data={"github_url": "http://github.com/owner/repo"})
    assert resp.status_code == 400


def test_fetch_github_rejects_malformed_path(client):
    c, _app_module, _tmp_path = client
    resp = c.post("/demo/fetch-github", data={"github_url": "https://github.com/just-an-owner"})
    assert resp.status_code == 400


# ── POST /demo/fetch-github — successful fetch (mocked network) ─────────────

def _fake_zip_bytes(root: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(f"{root}/{name}", content)
    return buf.getvalue()


class _FakeResponse:
    """Minimal stand-in for the context-managed response `urlopen()` returns."""

    def __init__(self, data: bytes):
        self._data = data
        self._sent = False

    def read(self, n=-1):
        if self._sent:
            return b""
        self._sent = True
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_github_success_extracts_and_returns_card(client, monkeypatch):
    c, _app_module, tmp_path = client
    monkeypatch.chdir(tmp_path)

    zip_bytes = _fake_zip_bytes("Hello-World-main", {"README.md": b"# Hello World\n"})

    def fake_urlopen(req, timeout=None):
        assert "codeload.github.com/octocat/Hello-World/zip/refs/heads/main" in req.full_url
        return _FakeResponse(zip_bytes)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = c.post("/demo/fetch-github", data={
        "github_url": "https://github.com/octocat/Hello-World/tree/main",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["github_url"] == "https://github.com/octocat/Hello-World"
    assert data["name"] == "octocat_Hello-World"
    assert (tmp_path / "examples" / "octocat_Hello-World" / "README.md").read_text() == "# Hello World\n"


def test_fetch_github_resolves_default_branch_when_no_ref_given(client, monkeypatch):
    """No `/tree/<ref>` in the URL — must hit the GitHub API for `default_branch`
    before downloading, and build the codeload URL from that, not a hardcoded 'main'."""
    c, _app_module, tmp_path = client
    monkeypatch.chdir(tmp_path)

    zip_bytes = _fake_zip_bytes("Hello-World-trunk", {"README.md": b"# Hello World\n"})
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if "api.github.com" in req.full_url:
            return _FakeResponse(json.dumps({"default_branch": "trunk"}).encode("utf-8"))
        assert "codeload.github.com/octocat/Hello-World/zip/refs/heads/trunk" in req.full_url
        return _FakeResponse(zip_bytes)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = c.post("/demo/fetch-github", data={"github_url": "https://github.com/octocat/Hello-World"})
    assert resp.status_code == 200
    assert len(calls) == 2
    assert "api.github.com/repos/octocat/Hello-World" in calls[0]


def test_fetch_github_rejects_zip_bomb(client, monkeypatch):
    """Uncompressed-size guard shared with /demo/upload — a payload whose
    ZipInfo.file_size claims to be far bigger than the cap must be rejected
    before anything is written to disk."""
    c, _app_module, tmp_path = client
    monkeypatch.chdir(tmp_path)

    zip_bytes = _fake_zip_bytes("Hello-World-main", {"big.bin": b"x"})

    import zipfile as zipfile_mod
    real_getinfo = zipfile_mod.ZipFile.getinfo

    def fake_getinfo(self, name):
        info = real_getinfo(self, name)
        info.file_size = 999 * 1024 * 1024
        return info

    monkeypatch.setattr(zipfile_mod.ZipFile, "getinfo", fake_getinfo)

    def fake_urlopen(req, timeout=None):
        return _FakeResponse(zip_bytes)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = c.post("/demo/fetch-github", data={
        "github_url": "https://github.com/octocat/Hello-World/tree/main",
    })
    assert resp.status_code == 413
    assert not (tmp_path / "examples" / "octocat_Hello-World").exists()


def test_fetch_github_surfaces_404_for_missing_repo(client, monkeypatch):
    import urllib.error

    c, _app_module, tmp_path = client
    monkeypatch.chdir(tmp_path)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = c.post("/demo/fetch-github", data={
        "github_url": "https://github.com/octocat/definitely-does-not-exist",
    })
    assert resp.status_code == 404
