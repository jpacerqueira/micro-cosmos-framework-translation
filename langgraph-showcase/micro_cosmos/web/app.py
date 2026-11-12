"""FastAPI web app — dashboard for the three-phase analysis pipeline.

Architecture:
- One orchestrator per active run (keyed by run_id)
- WebSocket relays PipelineEvents from the orchestrator to the browser
- HTTP POST endpoints for gate approvals/rejections
- HTMX-driven HTML over the wire
- Cytoscape.js renders the IR graph; bounded contexts overlaid once
  the Cartographer phase completes
"""

from __future__ import annotations

import asyncio
import html
import io
import json
import os
import secrets
import subprocess
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import litellm

from micro_cosmos import diagnostics
from micro_cosmos.orchestration import MicroCosmosOrchestrator
from micro_cosmos.orchestration.driver import run_full_pipeline
from micro_cosmos.orchestration.pipeline import PipelinePhase
from micro_cosmos.settings import get_settings
from micro_cosmos.tools.seam_tools import _detect_seams, _top_dir

# On 429 rate-limit: retry up to 4 times, waiting at least 65 s each time
# so the 60-second Anthropic token window fully resets before each retry.
litellm.num_retries = 4
litellm.retry_after = 65

_GATE_RESTART_PHASE: dict[str, PipelinePhase] = {
    "gate_1":            PipelinePhase.OBSERVER,
    "gate_2":            PipelinePhase.CARTOGRAPHER,
    "gate_3":            PipelinePhase.ARCHITECT,
    "gate_4":            PipelinePhase.SECURITY,
    "gate_4_5":          PipelinePhase.FEATURE_SPECIFIER,  # re-runs specifier before planning gate
    "gate_5":            PipelinePhase.CODE_WRITER,
    "feature_specifier": PipelinePhase.FEATURE_SPECIFIER,  # backward compat
}

_TDD_LOOP_PHASES = frozenset({
    PipelinePhase.CODE_WRITER,
    PipelinePhase.SKEPTICAL_REVIEW,
    PipelinePhase.TEST_REVIEW,
    PipelinePhase.FUNCTIONAL_REVIEW,
})

WEB_DIR = Path(__file__).parent


def static_url(path: str) -> str:
    """Cache-busting URL for a /static/<path> asset — appends the file's own
    mtime as a version query param, so a changed file always gets a fresh
    URL regardless of any browser/proxy caching policy in between."""
    file_path = WEB_DIR / "static" / path
    try:
        version = int(file_path.stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


class CacheControlledStaticFiles(StaticFiles):
    """StaticFiles that forces revalidation on every request (a cheap 304 if
    unchanged) instead of relying on browser heuristic caching, which can
    otherwise serve a stale asset for a while with no server round-trip at
    all — a second line of defense alongside static_url()'s cache-busting."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _extract_json(text: str) -> Any:
    import re
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))
TEMPLATES.env.globals["static_url"] = static_url

@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Reload saved runs once, when the process starts. Resolved at startup so the helper can be defined below."""
    await _restore_runs_from_disk()
    yield


app = FastAPI(
    title="Micro-Cosmos",
    description="Full pipeline: Observer → Cartographer → Architect → Security → Code Writer → PR Review",
    lifespan=_app_lifespan,
)
app.mount("/static", CacheControlledStaticFiles(directory=str(WEB_DIR / "static")), name="static")

_PUBLIC_PATHS = {"/login", "/healthz"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith("/static/") or request.session.get("authenticated"):
        return await call_next(request)
    return RedirectResponse(url="/login", status_code=303)


# Must be added AFTER require_login above — Starlette wraps middleware such
# that the LAST one added is OUTERMOST (runs first on the way in), so
# SessionMiddleware needs to be added last to populate request.session
# before require_login reads it. Verified: adding this before require_login
# raises "SessionMiddleware must be installed to access request.session".
app.add_middleware(
    SessionMiddleware,
    secret_key=get_settings().session_secret_key or secrets.token_hex(32),
    https_only=get_settings().session_https_only,
)


@app.exception_handler(Exception)
async def comprehension_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    debug_mode = request.headers.get("x-source-debug", "").lower() in {"true", "1", "yes"}
    diag = diagnostics.from_exception(
        exc,
        phase="http",
        source=f"{request.method} {request.url.path}",
        message=f"Unhandled exception: {type(exc).__name__}",
    )
    diagnostics.log.exception("HTTP handler crashed: %s %s", request.method, request.url.path)
    payload = diag.to_payload()
    if not debug_mode:
        payload = {**payload, "traceback": ""}
    return JSONResponse(status_code=500, content={"error": payload})


@app.exception_handler(HTTPException)
async def comprehension_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "severity": "ERROR" if exc.status_code >= 500 else "WARNING",
                "phase": "http",
                "source": f"{request.method} {request.url.path}",
                "message": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                "context": {"status_code": exc.status_code},
                "traceback": "",
            }
        },
    )


class Run:
    def __init__(
        self,
        run_id: str,
        source_path: str,
        source_lang: str,
        target_lang: str,
        skip_llm: bool = False,
        auto_approve_gates: bool = False,
        auto_approve_reviewer_name: str = "",
        github_url: str = "",
        pause_after_planning: bool = False,
    ) -> None:
        self.run_id = run_id
        self.source_path = source_path
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.skip_llm = skip_llm
        self.auto_approve_gates = auto_approve_gates
        self.auto_approve_reviewer_name = auto_approve_reviewer_name
        self.github_url = github_url
        self.pause_after_planning = pause_after_planning
        self.orchestrator = MicroCosmosOrchestrator(
            run_id,
            skip_llm=skip_llm,
            auto_approve_gates=auto_approve_gates,
            auto_approve_reviewer_name=auto_approve_reviewer_name,
            pause_after_planning=pause_after_planning,
        )
        self.queues: list[asyncio.Queue[str]] = []
        self.event_log: list[str] = []
        self._task: asyncio.Task | None = None
        self._restart_lock = asyncio.Lock()

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue()
        for line in self.event_log:
            q.put_nowait(line)
        self.queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        if q in self.queues:
            self.queues.remove(q)

    async def _broadcast(self, msg: str) -> None:
        self.event_log.append(msg)
        for q in self.queues:
            await q.put(msg)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run_pipeline())

    async def restart(self, start_phase: PipelinePhase) -> None:
        async with self._restart_lock:
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass

            self.orchestrator = MicroCosmosOrchestrator(
                self.run_id,
                skip_llm=self.skip_llm,
                auto_approve_gates=self.auto_approve_gates,
                auto_approve_reviewer_name=self.auto_approve_reviewer_name,
                pause_after_planning=self.pause_after_planning,
            )
            self.event_log.clear()
            self._task = asyncio.create_task(self._run_pipeline(start_phase=start_phase))

    async def _run_pipeline(self, start_phase: PipelinePhase | None = None) -> None:
        try:
            async for event in run_full_pipeline(
                self.orchestrator, self.source_path, self.source_lang, self.target_lang,
                start_phase=start_phase,
            ):
                await self._broadcast(event.to_json())
        except asyncio.CancelledError:
            await self._broadcast(json.dumps({
                "kind": "warning",
                "phase": "orchestrator",
                "payload": diagnostics.warning(
                    phase="orchestrator",
                    source="run",
                    message="Pipeline run cancelled.",
                ).to_payload(),
            }))
            raise
        except Exception as exc:
            diag = diagnostics.from_exception(
                exc,
                phase="orchestrator",
                source="run",
                message=f"Pipeline crashed: {type(exc).__name__}",
            )
            await self._broadcast(diagnostics.to_pipeline_event_json(diag))
            diagnostics.log.exception("Top-level pipeline failure")


RUNS: dict[str, Run] = {}
_MAX_RUNS = 20


def _get_run(run_id: str) -> Run:
    """Return the Run for run_id, restoring from disk if needed. Raises 404 if absent."""
    if run_id not in RUNS:
        _restore_run(run_id)
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    return RUNS[run_id]


def _restore_run(run_id: str) -> Run | None:
    """Reconstruct a Run from the on-disk run_meta.json (for post-restart access)."""
    meta_path = Path(get_settings().runs_dir) / run_id / "run_meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        run = Run(
            run_id, meta["source_path"], meta["source_lang"], meta["target_lang"],
            skip_llm=meta.get("skip_llm", False),
            auto_approve_gates=meta.get("auto_approve_gates", False),
            auto_approve_reviewer_name=meta.get("auto_approve_reviewer_name", ""),
            github_url=meta.get("github_url", ""),
            pause_after_planning=meta.get("pause_after_planning", False),
        )
        RUNS[run_id] = run
        return run
    except Exception:
        return None


async def _restore_runs_from_disk() -> None:
    """Load completed runs from disk so they remain browsable after a server restart."""
    runs_dir = Path(get_settings().runs_dir)
    if not runs_dir.exists():
        return
    loaded = 0
    for entry in sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not entry.is_dir() or entry.name in RUNS:
            continue
        if len(RUNS) >= _MAX_RUNS:
            break
        if _restore_run(entry.name):
            loaded += 1
    if loaded:
        diagnostics.log.info("Restored %d run(s) from disk on startup", loaded)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=303)
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": False})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    settings = get_settings()
    valid = secrets.compare_digest(username, settings.demo_username) and secrets.compare_digest(
        password, settings.demo_password
    )
    if not valid:
        return TEMPLATES.TemplateResponse(request, "login.html", {"error": True}, status_code=401)
    request.session["authenticated"] = True
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/demo", response_class=HTMLResponse)
async def demo_redirect():
    """The example chooser moved from /demo to / (2026-09-16). Kept as a
    permanent redirect so existing bookmarks, docs and screenshots still work.
    The /demo/* sub-routes below are API endpoints called by the page's own JS
    and deliberately keep their paths."""
    return RedirectResponse(url="/", status_code=308)


@app.post("/runs", response_class=HTMLResponse)
async def create_run(
    request: Request,
    source_path: str = Form(...),
    source_lang: str = Form(""),
    target_lang: str = Form(...),
    skip_llm: str = Form("false"),
    auto_approve_gates: str = Form("false"),
    auto_approve_reviewer_name: str = Form(""),
    github_url: str = Form(""),
    pause_after_planning: str = Form("false"),
):
    if not source_lang:
        from micro_cosmos.tools.observer_tools import detect_source_lang
        source_lang = detect_source_lang(source_path)
    from micro_cosmos.etl.catalog import pairing_error
    rejected = pairing_error(source_path, target_lang)
    if rejected:
        return HTMLResponse(
            f"<div class='warn'>{html.escape(rejected)}</div>",
            status_code=400,
        )
    skip_llm_bool = skip_llm.lower() == "true"
    auto_approve_gates_bool = auto_approve_gates.lower() == "true"
    pause_after_planning_bool = pause_after_planning.lower() == "true"
    auto_approve_reviewer_name = auto_approve_reviewer_name.strip()
    if auto_approve_gates_bool and not auto_approve_reviewer_name:
        return HTMLResponse(
            "<div class='warn'>Auto-approve requires an approver name.</div>",
            status_code=400,
        )
    run_id = uuid.uuid4().hex[:8]
    try:
        run = Run(
            run_id, source_path, source_lang, target_lang,
            skip_llm=skip_llm_bool,
            auto_approve_gates=auto_approve_gates_bool,
            auto_approve_reviewer_name=auto_approve_reviewer_name,
            github_url=github_url.strip(),
            pause_after_planning=pause_after_planning_bool,
        )
        RUNS[run_id] = run
        while len(RUNS) > _MAX_RUNS:
            del RUNS[next(iter(RUNS))]
        # Persist metadata so the run survives a server restart
        meta_path = Path(get_settings().runs_dir) / run_id / "run_meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps({
                "source_path": source_path, "source_lang": source_lang, "target_lang": target_lang,
                "skip_llm": skip_llm_bool,
                "auto_approve_gates": auto_approve_gates_bool,
                "auto_approve_reviewer_name": auto_approve_reviewer_name,
                "github_url": github_url.strip(),
                "pause_after_planning": pause_after_planning_bool,
            }),
            encoding="utf-8",
        )
        await run.start()
    except Exception as exc:
        diag = diagnostics.from_exception(
            exc, phase="bootstrap", source="create_run",
            message=f"Failed to start run: {type(exc).__name__}: {exc}",
        )
        diagnostics.log.exception("Failed to create run")
        return HTMLResponse(
            f"<div class='error-card'>"
            f"<strong>Could not start the run.</strong><br>"
            f"<code>{diag.message}</code>"
            f"<p class='hint'>Check the server logs for the full traceback.</p>"
            f"</div>",
            status_code=500,
        )
    return TEMPLATES.TemplateResponse(
        request,
        "_run_started.html",
        {"run_id": run_id, "source_path": source_path,
         "source_lang": source_lang, "target_lang": target_lang},
    )


_KNOWN_NON_OUTPUT = frozenset({"reports", "vectors"})
_REPORTS_NON_OUTPUT = frozenset({"vectors"})


_KIRO_POWERS_FOLDER = "kiro-dev-powers-app-modernization"
_OPENSPEC_FOLDER = "openspec"


def _scan_one_dir(directory: Path) -> tuple[str | None, str | None, str | None, str | None]:
    """Scan a single directory for output-code, skills, kiro-powers, and openspec subdirs.

    Returns (output_name, skills_name, kiro_name, openspec_name) — None if not found.
    """
    output_name: str | None = None
    skills_name: str | None = None
    kiro_name: str | None = None
    openspec_name: str | None = None
    try:
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in _REPORTS_NON_OUTPUT or entry.name.endswith((".json", ".zip", ".html")):
                continue
            if entry.name == _KIRO_POWERS_FOLDER:
                kiro_name = entry.name
            elif entry.name == _OPENSPEC_FOLDER:
                openspec_name = entry.name
            elif entry.name.endswith("_skills"):
                if skills_name is None:
                    skills_name = entry.name
            else:
                if output_name is None:
                    output_name = entry.name
    except Exception:
        pass
    return output_name, skills_name, kiro_name, openspec_name


def _scan_download_folders(run_dir: Path) -> dict[str, str | None]:
    """Return the actual folder names for output, skills, kiro powers, and openspec.

    New runs: all live under run_dir/reports/.
    Old runs (pre-migration): fall back to run_dir/ for any not found in reports/.
    Returns {"output": name_or_None, "skills": ..., "kiro": ..., "openspec": ...}.
    """
    output_name, skills_name, kiro_name, openspec_name = _scan_one_dir(run_dir / "reports")
    if output_name is None or skills_name is None:
        old_output, old_skills, _, _ = _scan_one_dir_root(run_dir)
        if output_name is None:
            output_name = old_output
        if skills_name is None:
            skills_name = old_skills
    return {
        "output": output_name, "skills": skills_name,
        "kiro": kiro_name, "openspec": openspec_name,
    }


def _scan_one_dir_root(run_dir: Path) -> tuple[str | None, str | None, str | None, str | None]:
    """Scan run_dir root — legacy layout used by old runs."""
    output_name: str | None = None
    skills_name: str | None = None
    kiro_name: str | None = None
    openspec_name: str | None = None
    try:
        for entry in sorted(run_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in _KNOWN_NON_OUTPUT or entry.name.endswith(".json"):
                continue
            if entry.name == _KIRO_POWERS_FOLDER:
                kiro_name = entry.name
            elif entry.name == _OPENSPEC_FOLDER:
                openspec_name = entry.name
            elif entry.name.endswith("_skills"):
                if skills_name is None:
                    skills_name = entry.name
            else:
                if output_name is None:
                    output_name = entry.name
    except Exception:
        pass
    return output_name, skills_name, kiro_name, openspec_name


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def view_run(request: Request, run_id: str):
    run = _get_run(run_id)

    # Pre-compute seam + work-stream data for inline embedding (no client fetch needed).
    # Prefer seam.json (has work/story-point fields); fall back to _detect_seams from IR.
    seam_data = None
    work_streams_data = None
    try:
        seam_data = run.orchestrator.load_artifact("seam")
        if seam_data is None:
            raw = run.orchestrator.load_artifact("ir_graph")
            if isinstance(raw, str):
                raw = _extract_json(raw)
            if isinstance(raw, dict) and "nodes" in raw:
                seam_data = _detect_seams(raw)
        work_streams_data = run.orchestrator.load_artifact("work_streams")
    except Exception:
        diagnostics.log.exception("view_run: seam pre-computation failed for %s", run_id)

    download_folders = _scan_download_folders(run.orchestrator.run_dir)
    reports_dir = run.orchestrator.run_dir / "reports"

    def _zip_ready(name: str | None) -> bool:
        return bool(name and (reports_dir / f"{name}.zip").exists())

    feature_specs_ready = (run.orchestrator.run_dir / "feature_specs.json").exists()

    return TEMPLATES.TemplateResponse(
        request,
        "run.html",
        {
            "run_id": run_id,
            "run": run,
            "seam_data": seam_data,
            "work_streams_data": work_streams_data,
            "download_output": download_folders["output"],
            "download_skills": download_folders["skills"],
            "download_kiro": download_folders["kiro"],
            # No "download_openspec" key — unlike skills/kiro (folder name varies,
            # the template needs the scanned name), OpenSpec's folder is always
            # literally "openspec" and run.html hardcodes that; only whether a zip
            # already exists (zip_openspec_ready below) is needed.
            "zip_output_ready": _zip_ready(download_folders["output"]),
            "zip_skills_ready": _zip_ready(download_folders["skills"]),
            "zip_kiro_ready": _zip_ready(download_folders["kiro"]),
            "zip_openspec_ready": _zip_ready(download_folders["openspec"]),
            "zip_full_ready": (reports_dir / f"{run_id}_full.zip").exists(),
            "feature_specs_ready": feature_specs_ready,
        },
    )


@app.websocket("/runs/{run_id}/events")
async def websocket_events(websocket: WebSocket, run_id: str):
    if not websocket.session.get("authenticated"):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    if run_id not in RUNS:
        _restore_run(run_id)
    if run_id not in RUNS:
        await websocket.close(code=4404)
        return
    run = RUNS[run_id]
    q = run.subscribe()
    try:
        while True:
            msg = await q.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        diagnostics.log.exception("WebSocket relay failed for run %s: %s", run_id, exc)
    finally:
        run.unsubscribe(q)


@app.get("/runs/{run_id}/artifacts/{key}")
async def get_artifact(run_id: str, key: str):
    orch = _get_run(run_id).orchestrator
    artifact = orch.load_artifact(key)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {key!r} not yet produced")
    if isinstance(artifact, str):
        artifact = _extract_json(artifact)
    return JSONResponse(artifact)


@app.get("/runs/{run_id}/graph", response_class=JSONResponse)
async def graph_data(run_id: str, level: str = "summary"):
    """Cytoscape.js elements for the IR property graph."""
    orch = _get_run(run_id).orchestrator

    def _get_artifact(key: str) -> Any:
        val = orch.load_artifact(key)
        if isinstance(val, str):
            val = _extract_json(val)
            if isinstance(val, str):
                val = None
        return val

    ir = _get_artifact("ir_graph")
    if not ir:
        return {"elements": []}

    ctx_map = _get_artifact("bounded_context_map")

    nodes_raw = ir.get("nodes", [])
    edges_raw = ir.get("edges", [])

    nodes_by_id: dict[str, dict] = {n["id"]: n for n in nodes_raw}
    all_node_ids = set(nodes_by_id)

    # ── Seam index ────────────────────────────────────────────────────────────
    # Annotate each PROGRAM node with its highest-priority seam (boundary >
    # object > preprocessing) and flag CALLS edges crossing link-seam dir pairs.
    _SEAM_PRIO = {"boundary": 3, "object": 2, "preprocessing": 1}
    node_seam: dict[str, dict] = {}
    link_seam_dirs: set[tuple[str, str]] = set()
    try:
        seam_result = _detect_seams(ir)
        for seam in seam_result.get("seams", []):
            if seam["type"] == "link":
                link_seam_dirs.add((
                    min(seam["side_a"].rstrip("/"), seam["side_b"].rstrip("/")),
                    max(seam["side_a"].rstrip("/"), seam["side_b"].rstrip("/")),
                ))
            else:
                nid = seam.get("location", "")
                if nid and (
                    nid not in node_seam
                    or _SEAM_PRIO.get(seam["type"], 0) > _SEAM_PRIO.get(node_seam[nid]["type"], 0)
                ):
                    node_seam[nid] = seam
    except Exception:
        diagnostics.log.exception("seam annotation failed — graph served without seam data")

    child_to_parent: dict[str, str] = {}
    for e in edges_raw:
        if e.get("type") == "DEFINES" and e["target_id"] in all_node_ids and e["source_id"] in all_node_ids:
            child_to_parent[e["target_id"]] = e["source_id"]

    prog_class_count: dict[str, int] = {}
    prog_method_count: dict[str, int] = {}
    prog_data_count: dict[str, int] = {}
    for nid, n in nodes_by_id.items():
        t = n.get("type", "")
        ancestor = nid
        while ancestor in child_to_parent:
            ancestor = child_to_parent[ancestor]
        if nodes_by_id.get(ancestor, {}).get("type") == "PROGRAM" and ancestor != nid:
            if t == "DATA_STRUCTURE":
                prog_class_count[ancestor] = prog_class_count.get(ancestor, 0) + 1
            elif t == "PROCEDURE":
                prog_method_count[ancestor] = prog_method_count.get(ancestor, 0) + 1
            elif t == "DATA_ITEM":
                prog_data_count[ancestor] = prog_data_count.get(ancestor, 0) + 1

    node_to_ctx: dict[str, str] = {}
    ctx_elements: list[dict[str, Any]] = []
    if ctx_map and "contexts" in ctx_map:
        for ctx in ctx_map["contexts"]:
            cid = f"ctx::{ctx['name']}"
            ctx_elements.append({
                "data": {
                    "id": cid,
                    "label": ctx["name"],
                    "confidence": ctx.get("confidence", "MEDIUM"),
                    "kind": "context",
                }
            })
            for nid in ctx.get("node_ids", []):
                node_to_ctx[nid] = cid

    if level == "summary":
        prog_ids = {n["id"] for n in nodes_raw if n.get("type") == "PROGRAM"}

        # Post-Cartographer: render a proper bounded context map — one labelled box
        # per context connected by cross-context CALLS arrows. Much cleaner than
        # showing individual files inside compound nodes.
        if ctx_map and "contexts" in ctx_map:
            elements: list[dict[str, Any]] = []
            valid_ctx_ids: set[str] = set()
            for ctx in ctx_map["contexts"]:
                cid = f"ctx::{ctx['name']}"
                prog_count = sum(1 for nid in ctx.get("node_ids", []) if nid in prog_ids)
                node_count = len(ctx.get("node_ids", []))
                # DeadCode has no PROGRAM nodes (all method-level) — show it if it has any nodes
                is_dead_code = ctx["name"] == "DeadCode"
                if prog_count == 0 and not is_dead_code:
                    continue
                if is_dead_code and node_count == 0:
                    continue
                valid_ctx_ids.add(cid)
                if is_dead_code:
                    method_count = sum(1 for nid in ctx.get("node_ids", []) if nid.startswith(("method.", "proc.")))
                    label = f"DeadCode\n{method_count} method{'s' if method_count != 1 else ''}"
                else:
                    label = f"{ctx['name']}\n{prog_count} file{'s' if prog_count != 1 else ''}"
                elements.append({
                    "data": {
                        "id": cid,
                        "label": label,
                        "name": ctx["name"],
                        "kind": "context",
                        "file_count": prog_count,
                        "node_count": node_count,
                        "confidence": ctx.get("confidence", 0.85),
                        "rationale": ctx.get("rationale", ""),
                    }
                })
            for i, pair in enumerate(ctx_map.get("cross_context_calls", [])):
                if not (isinstance(pair, list) and len(pair) == 2):
                    continue
                src_cid, tgt_cid = f"ctx::{pair[0]}", f"ctx::{pair[1]}"
                if src_cid in valid_ctx_ids and tgt_cid in valid_ctx_ids:
                    elements.append({
                        "data": {
                            "id": f"ctx_edge_{i}",
                            "source": src_cid,
                            "target": tgt_cid,
                            "label": "CALLS",
                            "kind": "ctx_edge",
                        }
                    })
            if elements:
                return {"elements": elements, "level": "summary"}

        # Pre-Cartographer fallback: flat PROGRAM-node graph (no grouping yet)
        elements: list[dict[str, Any]] = []
        for n in nodes_raw:
            if n.get("type") != "PROGRAM":
                continue
            nid = n["id"]
            classes = prog_class_count.get(nid, 0)
            methods = prog_method_count.get(nid, 0)
            data: dict[str, Any] = {
                "id": nid,
                "label": "\n".join([n["name"]] + ([f"{classes}cls · {methods}fn"] if classes or methods else [])),
                "type": "PROGRAM",
                "kind": "ir_node",
                "summary": n.get("summary", ""),
                "inputs": n.get("inputs", []),
                "output": n.get("output", ""),
            }
            seam = node_seam.get(nid)
            if seam:
                data["seam_type"] = seam["type"]
                data["seam_note"] = seam.get("substitution_note", "")
                data["seam_evidence"] = "; ".join(seam.get("evidence", []))
            elements.append({"data": data})

        seen_edge: set[tuple] = set()
        for i, e in enumerate(edges_raw):
            src, tgt, etype = e.get("source_id", ""), e.get("target_id", ""), e.get("type", "")
            if etype == "DEFINES":
                continue

            def prog_ancestor(nid: str) -> str:
                seen: set[str] = set()
                while nid in child_to_parent and nid not in seen:
                    seen.add(nid)
                    nid = child_to_parent[nid]
                return nid

            src_prog = prog_ancestor(src)
            tgt_prog = prog_ancestor(tgt)
            if src_prog not in prog_ids or tgt_prog not in prog_ids:
                continue
            if src_prog == tgt_prog:
                continue
            key = (src_prog, tgt_prog, etype)
            if key in seen_edge:
                continue
            seen_edge.add(key)
            elements.append({
                "data": {
                    "id": f"e{i}",
                    "source": src_prog,
                    "target": tgt_prog,
                    "label": etype,
                    "kind": "ir_edge",
                }
            })
        return {"elements": elements, "level": "summary"}

    else:
        # Full view: flat hierarchy — dagre LR ranks file nodes at the top,
        # classes below via DEFINES edges. Nodes are colour-coded by bounded
        # context so the same palette from the Repo Map carries through.
        elements: list[dict[str, Any]] = []

        # Build context palette index: same order as ctx_map["contexts"]
        ctx_palette_idx: dict[str, int] = {}
        if ctx_map and "contexts" in ctx_map:
            _prog_ids_tmp = {n["id"] for n in nodes_raw if n.get("type") == "PROGRAM"}
            _idx = 0
            for ctx in ctx_map["contexts"]:
                cid = f"ctx::{ctx['name']}"
                if any(nid in _prog_ids_tmp for nid in ctx.get("node_ids", [])):
                    ctx_palette_idx[cid] = _idx
                    _idx += 1

        for n in nodes_raw:
            nid = n["id"]
            data = {
                "id": nid,
                "label": n["name"],
                "type": n.get("type", ""),
                "kind": "ir_node",
                "summary": n.get("summary", ""),
                "inputs": n.get("inputs", []),
                "output": n.get("output", ""),
            }
            ctx_id = node_to_ctx.get(nid)
            if ctx_id and ctx_id in ctx_palette_idx:
                data["ctx_index"] = ctx_palette_idx[ctx_id]
                data["ctx_name"] = ctx_id.replace("ctx::", "")
            elements.append({"data": data})

        for i, e in enumerate(edges_raw):
            src, tgt = e.get("source_id", ""), e.get("target_id", "")
            if src not in all_node_ids or tgt not in all_node_ids:
                continue
            etype = e.get("type", "")
            elements.append({
                "data": {
                    "id": f"e{i}",
                    "source": src,
                    "target": tgt,
                    "label": etype,
                    "kind": "ir_edge",
                }
            })
        return {"elements": elements, "level": "full"}


@app.get("/runs/{run_id}/gates", response_class=JSONResponse)
async def gate_states(run_id: str):
    return _get_run(run_id).orchestrator.gate_state_snapshot()


def _check_gate_token(request: Request) -> None:
    token = get_settings().gate_token
    if token and request.headers.get("x-gate-token", "") != token:
        raise HTTPException(status_code=403, detail="Invalid gate token")


@app.post("/runs/{run_id}/gates/{gate_id}/approve", response_class=HTMLResponse)
async def approve_gate_endpoint(
    request: Request,
    run_id: str,
    gate_id: str,
    reviewer_name: str = Form(...),
    notes: str = Form(""),
):
    _check_gate_token(request)
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    orch = RUNS[run_id].orchestrator
    try:
        orch.approve_gate(gate_id, reviewer_name=reviewer_name, notes=notes)
    except KeyError:
        return HTMLResponse(
            f"<div class='warn'>Unknown gate <code>{gate_id}</code>.</div>", status_code=400
        )
    except Exception as exc:
        diagnostics.log.exception("approve_gate failed for %s/%s", run_id, gate_id)
        return HTMLResponse(
            f"<div class='warn'>Approval failed: {type(exc).__name__}: {exc}</div>",
            status_code=500,
        )
    return HTMLResponse(
        f"<div class='ok'>Gate {gate_id} approved by {reviewer_name}.</div>"
    )


@app.post("/runs/{run_id}/gates/{gate_id}/reject", response_class=HTMLResponse)
async def reject_gate_endpoint(
    request: Request,
    run_id: str,
    gate_id: str,
    reviewer_name: str = Form(...),
    reason: str = Form(...),
):
    _check_gate_token(request)
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    orch = RUNS[run_id].orchestrator
    try:
        constraint = await orch.reject_gate(
            gate_id, reviewer_name=reviewer_name, reason=reason
        )
    except (KeyError, ValueError):
        return HTMLResponse(
            f"<div class='warn'>Unknown gate <code>{gate_id}</code>.</div>", status_code=400
        )
    except Exception as exc:
        diagnostics.log.exception("reject_gate failed for %s/%s", run_id, gate_id)
        return HTMLResponse(
            f"<div class='warn'>Rejection failed: {type(exc).__name__}: {exc}</div>",
            status_code=500,
        )
    return HTMLResponse(
        f"<div class='warn'>Gate {gate_id} rejected. "
        f"Constraint <code>{constraint.sha}</code> will apply on retry.</div>"
    )


@app.post("/runs/{run_id}/restart", response_class=HTMLResponse)
async def restart_run(
    request: Request,
    run_id: str,
    from_gate: str = Form(...),
):
    _check_gate_token(request)
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    if from_gate not in _GATE_RESTART_PHASE:
        return HTMLResponse(
            f"<div class='warn'>Unknown gate <code>{from_gate}</code>. "
            f"Valid values: {', '.join(_GATE_RESTART_PHASE)}.</div>",
            status_code=400,
        )
    start_phase = _GATE_RESTART_PHASE[from_gate]
    try:
        await RUNS[run_id].restart(start_phase)
    except Exception as exc:
        diagnostics.log.exception("restart failed for %s/%s", run_id, from_gate)
        return HTMLResponse(
            f"<div class='warn'>Restart failed: {type(exc).__name__}: {exc}</div>",
            status_code=500,
        )
    return HTMLResponse(
        f"<div class='ok'>Restarting from <strong>{start_phase.value}</strong>…</div>"
    )


@app.post("/runs/{run_id}/stop-tdd-loop", response_class=HTMLResponse)
async def stop_tdd_loop(request: Request, run_id: str):
    _check_gate_token(request)
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    run = RUNS[run_id]
    orch = run.orchestrator
    if orch.current_phase not in _TDD_LOOP_PHASES:
        return HTMLResponse(
            "<div class='warn'>No TDD loop is currently running for this run.</div>",
            status_code=400,
        )
    if orch.stop_requested:
        return HTMLResponse("<div class='ok'>Stop already requested — finishing current step…</div>")
    orch.stop_requested = True
    await run._broadcast(json.dumps({
        "kind": "tdd_loop_stop_requested",
        "phase": orch.current_phase.value,
        "payload": {"message": "Stop requested — will halt after the current phase/iteration finishes."},
    }))
    return HTMLResponse("<div class='ok'>Stop requested — finishing current step…</div>")


_FILE_TO_SCRIPT = {
    "migration-briefing.html":     "generate_briefing.js",
    "ir-graph.html":               "generate_graph.js",
    "project-synthesis.html":      "generate_synthesis.js",
    # New reports
    "executive-summary.html":      "generate_exec_summary.js",
    "hotspots.html":               "generate_hotspots.js",
    "sprint-plan.html":            "generate_sprint_plan.js",
    "architecture-decisions.html": "generate_adrs.js",
    "fitness-stubs.html":          "generate_fitness_stubs.js",
    "dead-code.html":              "generate_deadcode.js",
    "security-report.html":        "generate_security.js",
    "output-security-report.html": "generate_output_security.js",
    "feature-specs.html":          "generate_feature_specs.js",
    "monitoring.html":             "generate_monitoring.js",
    # Must stay last: within _generate_all_available_reports()'s loop below
    # (plain dict insertion order), this guarantees every other report is
    # attempted before the combined report's own turn runs.
    "full-app-migration-report.html": "generate_full_report.js",
}

# Sidebar of the in-app report browser. Every key in _FILE_TO_SCRIPT appears once.
_REPORT_BROWSER: list[tuple[str, list[tuple[str, str]]]] = [
    ("Full report", [
        ("full-app-migration-report.html", "Full migration report"),
    ]),
    ("Stakeholder", [
        ("executive-summary.html", "Executive summary"),
        ("migration-briefing.html", "Migration briefing"),
    ]),
    ("Analysis", [
        ("project-synthesis.html", "Project synthesis"),
        ("hotspots.html", "Hotspots & coupling"),
        ("dead-code.html", "Dead code & waste"),
        ("architecture-decisions.html", "Architecture decisions"),
        ("fitness-stubs.html", "Fitness test stubs"),
        ("monitoring.html", "Telemetry gap analysis"),
    ]),
    ("Security", [
        ("security-report.html", "Source security analysis"),
        ("output-security-report.html", "Output security scan"),
    ]),
    ("Pipeline", [
        ("ir-graph.html", "IR graph"),
        ("sprint-plan.html", "Migration sprint plan"),
        ("feature-specs.html", "Build output features"),
    ]),
]
_REPORT_LABELS = {filename: label for _, items in _REPORT_BROWSER for filename, label in items}

_CODE_SUFFIXES = frozenset({
    ".sql", ".sqlx", ".py", ".java", ".kt", ".kts", ".scala", ".go", ".rs",
    ".cs", ".js", ".ts", ".tsx", ".jsx", ".swift", ".yml", ".yaml", ".json",
    ".xml", ".md", ".markdown", ".gradle", ".properties", ".toml", ".tf",
    ".hcl", ".css", ".html", ".sh", ".bash", ".ipynb", ".csv", ".txt",
    ".cfg", ".ini", ".conf", ".kiro",
})
_CODE_NAMES = frozenset({"Dockerfile", "Makefile"})
_SKIP_CODE_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "target",
    ".gradle", "dist", "build", ".idea",
})
_MAX_CODE_FILES = 400
_MAX_CODE_BYTES = 200_000

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"

# Maps report filename → the run-root JSON artifact required before the Node script runs.
_REPORT_PREREQUISITES: dict[str, str] = {
    "feature-specs.html":          "feature_specs.json",
    "output-security-report.html": "trivy_output_report.json",
    "sprint-plan.html":            "work_streams.json",
    "migration-briefing.html":     "work_streams.json",
    "project-synthesis.html":      "work_streams.json",
}


def _report_not_ready_html(filename: str, prereq: str, run_id: str, is_active: bool) -> str:
    """Self-contained HTML page shown when a report's required input artifact is missing."""
    css = (
        "body{font-family:'IBM Plex Mono',monospace;max-width:680px;margin:80px auto;"
        "padding:0 24px;color:#1a1a1a;line-height:1.6}"
        "h2{font-size:1.1rem;margin-bottom:8px}"
        "p{margin:6px 0}code,pre{background:#f5f5f5;padding:2px 6px;border-radius:3px;"
        "font-size:0.9rem}pre{display:block;padding:12px;overflow-x:auto;margin:12px 0}"
        ".muted{color:#666;font-size:0.85rem}"
    )
    if is_active:
        heading    = "⏳ Report not yet available"
        extra_head = '<meta http-equiv="refresh" content="20">'
        body = (
            f"<p>The pipeline is still running — <code>{prereq}</code> has not been "
            f"written yet.</p>"
            f"<p>This page refreshes automatically every 20 seconds. "
            f"Come back once the pipeline completes and the report will generate instantly.</p>"
            f'<p class="muted">Run {run_id}</p>'
        )
    else:
        heading    = "⚠ Report unavailable"
        extra_head = ""
        if prereq == "feature_specs.json":
            body = (
                f"<p><code>{prereq}</code> was not produced by this run. "
                f"The <strong>FEATURE_SPECIFIER</strong> phase did not execute.</p>"
                f"<p>Regenerate without re-running all seams:</p>"
                f"<pre>curl -X POST http://localhost:8080/runs/{run_id}/restart \\\n"
                f'     -d "from_gate=feature_specifier"</pre>'
                f'<p class="muted">Run {run_id}</p>'
            )
        elif prereq == "work_streams.json":
            body = (
                f"<p><code>{prereq}</code> was not produced by this run.</p>"
                f"<p>This file is written by the <strong>OBSERVER</strong> and "
                f"<strong>CARTOGRAPHER</strong> analysis phases. It may be missing if "
                f"the run used an older Docker image (before the deterministic-mode fix) "
                f"or if the analysis phases failed.</p>"
                f"<p>Restart the pipeline from the beginning to regenerate it:</p>"
                f"<pre>curl -X POST http://localhost:8080/runs/{run_id}/restart \\\n"
                f'     -d "from_gate=gate_1"</pre>'
                f'<p class="muted">Run {run_id}</p>'
            )
        else:
            body = (
                f"<p><code>{prereq}</code> was not produced by this run. "
                f"The pipeline may not have completed all phases.</p>"
                f'<p class="muted">Run {run_id}</p>'
            )
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{heading}</title>{extra_head}"
        f"<style>{css}</style></head>"
        f"<body><h2>{heading}</h2>{body}</body></html>"
    )


async def _generate_report_file(script: Path, run_dir: Path, out_path: Path) -> None:
    """Run a scripts/generate_*.js report generator. Raises on any failure —
    missing script, non-zero exit, timeout, or no output file produced."""
    if not script.exists():
        raise FileNotFoundError(f"{script.name} not found")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            ["node", str(script), str(run_dir), str(out_path)],
            capture_output=True, text=True, timeout=60,
        ),
    )
    if r.returncode != 0 or not out_path.exists():
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])


async def _generate_all_available_reports(run: "Run", run_dir: Path, reports_dir: Path) -> None:
    """Best-effort: build every report/artifact that can be generated right
    now and isn't already on disk — as if every item in the "Reports Skills
    and Code" menu had been clicked. Used before the "full" zip is built so
    the zip reflects the run's complete current state, not just whichever
    reports happened to be opened already.

    Each report is independent: one that's missing its prerequisite artifact,
    or that fails to generate, is skipped — never fatal to the others.
    """
    for filename, script_name in _FILE_TO_SCRIPT.items():
        out_path = reports_dir / filename
        if out_path.exists():
            continue
        prereq = _REPORT_PREREQUISITES.get(filename)
        if prereq and not (run_dir / prereq).exists():
            continue
        try:
            await _generate_report_file(_SCRIPTS_DIR / script_name, run_dir, out_path)
        except Exception as exc:
            diagnostics.log.warning("full-zip: skipped %s (%s)", filename, exc)

    # OpenAPI spec / Jira export share feature_specs.json as their only
    # prerequisite, but their routes only ever stream a response in memory —
    # persist a copy under reports/ too, so the full zip actually contains a
    # file for them instead of nothing.
    if (run_dir / "feature_specs.json").exists():
        openapi_path = reports_dir / "openapi.yaml"
        if not openapi_path.exists():
            try:
                from micro_cosmos.tools.feature_spec_tools import export_openapi as _export_openapi
                yaml_text = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _export_openapi(str(run_dir))
                )
                openapi_path.write_text(yaml_text, encoding="utf-8")
            except Exception as exc:
                diagnostics.log.warning("full-zip: skipped openapi.yaml (%s)", exc)

        # A run created before the openspec->openapi rename may still have the old
        # file on disk; without this, a rebuilt full zip would ship both the stale
        # mislabeled file and the new correctly-named one side by side.
        stale_openspec_yaml = reports_dir / "openspec.yaml"
        if stale_openspec_yaml.exists():
            try:
                stale_openspec_yaml.unlink()
            except OSError as exc:
                diagnostics.log.warning("full-zip: could not remove stale openspec.yaml (%s)", exc)

        jira_path = reports_dir / "jira_bulk_import.json"
        if not jira_path.exists():
            try:
                from micro_cosmos.tools.feature_spec_tools import export_jira as _export_jira
                payload = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _export_jira(str(run_dir), "ALX")
                )
                jira_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception as exc:
                diagnostics.log.warning("full-zip: skipped jira_bulk_import.json (%s)", exc)

    # Kiro.dev Powers / Claude Code skills are pure templates with no real
    # seam-output dependency (see driver.py's identical call site in
    # _run_all_seams(), which explicitly runs these in both LLM and
    # deterministic modes) — producible regardless of pipeline stage as long
    # as source/target language are known, which they are from run creation.
    kiro_dst = reports_dir / "kiro-dev-powers-app-modernization"
    if not kiro_dst.exists():
        try:
            from micro_cosmos.tools.writer_tools import _write_kiro_powers
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _write_kiro_powers(
                    run_path=run_dir,
                    source_path=run.source_path,
                    source_lang=run.source_lang,
                    target_lang=run.target_lang,
                ),
            )
        except Exception as exc:
            diagnostics.log.warning("full-zip: skipped kiro-dev-powers (%s)", exc)

    try:
        from micro_cosmos.tools.writer_tools import _project_dir_name, _write_output_skills
        proj_dir = _project_dir_name(run.source_path, run.target_lang)
        skills_dst = reports_dir / f"{proj_dir}_skills"
        if not skills_dst.exists():
            seam_data = run.orchestrator.load_artifact("seam") or {}
            seams_list = seam_data.get("seams") or []
            first_seam = seams_list[0].get("id", "project") if seams_list else "project"
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _write_output_skills(
                    source_path=run.source_path,
                    source_lang=run.source_lang,
                    target_lang=run.target_lang,
                    seam_name=first_seam,
                    run_path=run_dir,
                    project_dir=proj_dir,
                ),
            )
    except Exception as exc:
        diagnostics.log.warning("full-zip: skipped skills directory (%s)", exc)

    # OpenSpec — unlike Kiro Powers/skills above, this is derived from
    # feature_specs.json/tnas.json/security_report.json and must reflect
    # whatever is CURRENT at zip time, not a stale copy from an earlier gate
    # cycle — so this always re-runs the writer, never guarded by exists().
    if (run_dir / "feature_specs.json").exists() or (run_dir / "tnas.json").exists():
        try:
            from micro_cosmos.tools.writer_tools import _write_openspec
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _write_openspec(
                    run_path=run_dir,
                    source_path=run.source_path,
                    source_lang=run.source_lang,
                    target_lang=run.target_lang,
                ),
            )
        except Exception as exc:
            diagnostics.log.warning("full-zip: skipped openspec (%s)", exc)

    # "Translated code" (write_output_files(), keyed off seam_result.json) is
    # deliberately NOT attempted here — it requires real Code Writer output
    # for at least one seam, which cannot be synthesized on demand. If it
    # doesn't exist yet, the full zip simply won't include it.

    # Full report — regenerated unconditionally, a second time, after every
    # other artifact above has had its turn. The loop at the top of this
    # function already generates full-app-migration-report.html once (it's the last key in
    # _FILE_TO_SCRIPT), but that first pass runs BEFORE openapi/jira/kiro/
    # skills/openspec exist yet, so its status table would show them as "not
    # yet generated" even though they're created moments later in this same
    # request. Regenerating here — now that everything above has run — makes
    # the copy bundled into full.zip accurate on the very first click.
    try:
        await _generate_report_file(
            _SCRIPTS_DIR / "generate_full_report.js", run_dir, reports_dir / "full-app-migration-report.html"
        )
    except Exception as exc:
        diagnostics.log.warning("full-zip: skipped final full-app-migration-report.html regeneration (%s)", exc)


_NON_CODE_DIRS = frozenset({"source_vectors", "vectors", "reports"})


def _translated_root(run_dir: Path) -> Path | None:
    """Directory of the generated destination project, when the run wrote one.

    ``reports/project_dir.txt`` is the name the writer reserved. Vector indexes
    under the run root are not that project.
    """
    marker = run_dir / "reports" / "project_dir.txt"
    if marker.is_file():
        name = marker.read_text(encoding="utf-8").strip()
        if not name or "/" in name or "\\" in name or ".." in name:
            return None
        for candidate in (run_dir / "reports" / name, run_dir / name):
            if candidate.is_dir():
                return candidate
        return None
    name = _scan_download_folders(run_dir).get("output")
    if not name or name in _NON_CODE_DIRS or name.endswith("_vectors"):
        return None
    for candidate in (run_dir / "reports" / name, run_dir / name):
        if candidate.is_dir():
            return candidate
    return None


_PACK_LABELS = {
    "kiro": "Kiro.dev Powers",
    "skills": "Claude Code skills",
    "openspec": "OpenSpec",
}
_PACK_HIDDEN_DIRS = frozenset({".kiro", ".claude"})
_PACK_HIDDEN_FILES = frozenset({".config.kiro"})


def _is_code_file(path: Path) -> bool:
    if path.name in _CODE_NAMES:
        return True
    return any(suffix.lower() in _CODE_SUFFIXES for suffix in path.suffixes)


def _iter_text_files(root: Path, *, include_hidden: bool = False) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        kept_dirs = []
        for name in sorted(dirnames):
            if name in _SKIP_CODE_DIRS:
                continue
            if name.startswith(".") and not (include_hidden and name in _PACK_HIDDEN_DIRS):
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            if name == ".env":
                continue
            if name.startswith(".") and not (include_hidden and name in _PACK_HIDDEN_FILES):
                continue
            path = Path(dirpath) / name
            if not _is_code_file(path):
                continue
            found.append(path.relative_to(root).as_posix())
            if len(found) >= _MAX_CODE_FILES:
                return found
    return found


def _iter_translated_files(root: Path) -> list[str]:
    return _iter_text_files(root)


def _resolve_translated_file(root: Path, rel: str) -> Path:
    rel = rel.replace("\\", "/").lstrip("/")
    parts = rel.split("/") if rel else []
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise HTTPException(status_code=404, detail="File not found")
    dest = (root / rel).resolve()
    base = root.resolve()
    if dest != base and base not in dest.parents:
        raise HTTPException(status_code=404, detail="File not found")
    if not dest.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not _is_code_file(dest):
        raise HTTPException(status_code=404, detail="File not found")
    return dest


def _pack_root(run_dir: Path, kind: str) -> Path | None:
    if kind not in _PACK_LABELS:
        return None
    name = _scan_download_folders(run_dir).get(kind)
    if not name:
        return None
    for candidate in (run_dir / "reports" / name, run_dir / name):
        if candidate.is_dir():
            return candidate
    return None


def _browser_page(
    request: Request,
    run_id: str,
    *,
    view: str,
    filename: str,
    code_path: str,
    frame_src: str,
    current_label: str,
    pack_kind: str = "",
):
    run = _get_run(run_id)
    run_dir = run.orchestrator.run_dir
    packs = []
    for kind, label in _PACK_LABELS.items():
        root = _pack_root(run_dir, kind)
        if root is None:
            continue
        files = [
            {
                "path": rel,
                "href": f"/runs/{run_id}/browse/pack/{kind}/{quote(rel, safe='/')}",
            }
            for rel in _iter_text_files(root, include_hidden=True)
        ]
        if files:
            packs.append({"kind": kind, "name": label, "files": files})
    code_root = _translated_root(run_dir)
    code_files = []
    if code_root is not None:
        for rel in _iter_translated_files(code_root):
            code_files.append({
                "path": rel,
                "href": f"/runs/{run_id}/browse/code/{quote(rel, safe='/')}",
            })
    groups = [
        {
            "name": name,
            "reports": [{"filename": item_name, "label": label} for item_name, label in items],
        }
        for name, items in _REPORT_BROWSER
    ]
    return TEMPLATES.TemplateResponse(
        request,
        "report_browser.html",
        {
            "run_id": run_id,
            "groups": groups,
            "packs": packs,
            "code_files": code_files,
            "view": view,
            "filename": filename,
            "code_path": code_path,
            "pack_kind": pack_kind,
            "frame_src": frame_src,
            "current_label": current_label,
        },
    )


@app.get("/runs/{run_id}/browse")
async def browse_reports_home(run_id: str):
    _get_run(run_id)
    return RedirectResponse(
        url=f"/runs/{run_id}/browse/full-app-migration-report.html",
        status_code=302,
    )


@app.get("/runs/{run_id}/browse/pack/{kind}/{file_path:path}")
async def browse_pack_file(request: Request, run_id: str, kind: str, file_path: str):
    if kind not in _PACK_LABELS:
        raise HTTPException(status_code=404, detail="Folder not found")
    run = _get_run(run_id)
    root = _pack_root(run.orchestrator.run_dir, kind)
    if root is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    _resolve_translated_file(root, file_path)
    return _browser_page(
        request,
        run_id,
        view="pack",
        filename="",
        code_path=file_path,
        pack_kind=kind,
        frame_src=f"/runs/{run_id}/pack/{kind}/{quote(file_path, safe='/')}",
        current_label=file_path,
    )


@app.get("/runs/{run_id}/pack/{kind}/{file_path:path}")
async def pack_file_view(request: Request, run_id: str, kind: str, file_path: str):
    if kind not in _PACK_LABELS:
        raise HTTPException(status_code=404, detail="Folder not found")
    run = _get_run(run_id)
    root = _pack_root(run.orchestrator.run_dir, kind)
    if root is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    dest = _resolve_translated_file(root, file_path)
    raw = dest.read_bytes()
    truncated = len(raw) > _MAX_CODE_BYTES
    text = raw[:_MAX_CODE_BYTES].decode("utf-8", errors="replace")
    return TEMPLATES.TemplateResponse(
        request,
        "code_view.html",
        {"path": file_path, "content": text, "truncated": truncated},
    )


@app.get("/runs/{run_id}/browse/code/{file_path:path}")
async def browse_translated_code(request: Request, run_id: str, file_path: str):
    run = _get_run(run_id)
    root = _translated_root(run.orchestrator.run_dir)
    if root is None:
        raise HTTPException(status_code=404, detail="No translated project")
    _resolve_translated_file(root, file_path)
    return _browser_page(
        request,
        run_id,
        view="code",
        filename="",
        code_path=file_path,
        frame_src=f"/runs/{run_id}/translated/{quote(file_path, safe='/')}",
        current_label=file_path,
    )


@app.get("/runs/{run_id}/translated/{file_path:path}")
async def translated_file_view(request: Request, run_id: str, file_path: str):
    run = _get_run(run_id)
    root = _translated_root(run.orchestrator.run_dir)
    if root is None:
        raise HTTPException(status_code=404, detail="No translated project")
    dest = _resolve_translated_file(root, file_path)
    raw = dest.read_bytes()
    truncated = len(raw) > _MAX_CODE_BYTES
    text = raw[:_MAX_CODE_BYTES].decode("utf-8", errors="replace")
    return TEMPLATES.TemplateResponse(
        request,
        "code_view.html",
        {"path": file_path, "content": text, "truncated": truncated},
    )


@app.get("/runs/{run_id}/browse/{filename}")
async def browse_report(request: Request, run_id: str, filename: str):
    if filename not in _FILE_TO_SCRIPT:
        raise HTTPException(status_code=404, detail="Report not found")
    _get_run(run_id)
    return _browser_page(
        request,
        run_id,
        view="report",
        filename=filename,
        code_path="",
        frame_src=f"/runs/{run_id}/files/{filename}",
        current_label=_REPORT_LABELS[filename],
    )


@app.get("/runs/{run_id}/files/{filename}")
async def run_file(run_id: str, filename: str):
    if filename not in _FILE_TO_SCRIPT:
        raise HTTPException(status_code=404, detail="File not found")
    run         = _get_run(run_id)
    run_dir     = run.orchestrator.run_dir
    reports_dir = run_dir / "reports"
    out_path    = reports_dir / filename

    # ── Prerequisite guard — return a friendly HTML page instead of a 500 ────
    prereq = _REPORT_PREREQUISITES.get(filename)
    if prereq and not (run_dir / prereq).exists():
        is_active = run._task is not None and not run._task.done()
        return HTMLResponse(
            _report_not_ready_html(filename, prereq, run_id, is_active),
            status_code=202 if is_active else 404,
        )

    # full-app-migration-report.html always regenerates — it's a live status snapshot of
    # every other artifact, so a stale cached copy would defeat its purpose
    # (same "always regenerate" precedent as OpenSpec's _write_openspec()).
    if filename == "full-app-migration-report.html" or not out_path.exists():
        script = _SCRIPTS_DIR / _FILE_TO_SCRIPT[filename]
        try:
            await _generate_report_file(script, run_dir, out_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"{filename} has not been generated yet") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Generation failed: {exc}") from exc
    return FileResponse(
        out_path,
        media_type="text/html",
        filename=filename,
        content_disposition_type="inline",
    )


def _resolve_zip_target(run_dir: Path, run_id: str, folder_type: str) -> tuple[Path, Path, Path]:
    """Resolve (target, reports_dir, zip_path) for a given zip folder_type.

    "full" zips the entire run_dir (all artifacts, reports/, generated code —
    everything); the other three zip a single named subfolder inside it.
    Raises HTTPException(404) if the requested folder doesn't exist yet.
    """
    reports_dir = run_dir / "reports"
    if folder_type == "full":
        return run_dir, reports_dir, reports_dir / f"{run_id}_full.zip"

    folders = _scan_download_folders(run_dir)
    folder_name = folders[folder_type]
    if not folder_name:
        _labels = {"skills": "Skills", "kiro": "Kiro powers", "openspec": "OpenSpec"}
        label = _labels.get(folder_type, "Output code")
        raise HTTPException(status_code=404, detail=f"{label} folder not yet generated.")

    # New layout: folder lives inside reports/; old layout: folder at run_dir root
    target = reports_dir / folder_name if (reports_dir / folder_name).is_dir() else run_dir / folder_name
    return target, reports_dir, reports_dir / f"{folder_name}.zip"


@app.post("/runs/{run_id}/zip/{folder_type}")
async def generate_zip(run_id: str, folder_type: str):
    """Generate a .zip of the output-code, skills, kiro-powers, openspec, or
    entire run folder and persist it to disk, overwriting any previous zip at
    the same path — a second request always rebuilds from the run's current
    state.

    Returns {"filename": "<name>.zip", "size": <bytes>} on success.
    The saved file is served by GET /runs/{run_id}/download/{folder_type}.
    """
    if folder_type not in ("output", "skills", "kiro", "openspec", "full"):
        raise HTTPException(
            status_code=400,
            detail="folder_type must be 'output', 'skills', 'kiro', 'openspec', or 'full'",
        )

    run = _get_run(run_id)
    run_dir = run.orchestrator.run_dir

    if folder_type == "openspec":
        # Unlike skills/kiro (frozen templates, content never changes once
        # written — see driver.py's guarded call), OpenSpec content is
        # derived from feature_specs.json/tnas.json/security_report.json,
        # which CAN legitimately change (a Gate 3/4.5 rejection + re-run).
        # Every Generate/Regenerate click must refresh content before
        # zipping — there is no meaningful "skip if already generated" case
        # here, and calling this unconditionally also makes the very first
        # click self-sufficient even if driver.py's automatic call hasn't
        # run yet (e.g. a deterministic-mode run, or one that hasn't
        # reached Gate 4.5).
        from micro_cosmos.tools.writer_tools import _write_openspec
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _write_openspec(
                    run_path=run_dir,
                    source_path=run.source_path,
                    source_lang=run.source_lang,
                    target_lang=run.target_lang,
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"OpenSpec generation failed: {exc}") from exc

    target, reports_dir, zip_path = _resolve_zip_target(run_dir, run_id, folder_type)
    zip_name = zip_path.name

    if folder_type == "full":
        await _generate_all_available_reports(run, run_dir, reports_dir)

    def _build_and_save() -> int:
        reports_dir.mkdir(parents=True, exist_ok=True)
        # zipfile.ZipFile(path, "w") truncates any existing file at zip_path
        # in place — no rename/locking involved, matching this codebase's
        # existing write pattern for everything else under runs/ (see
        # transferable-skills/memory/gcp-deployment.md's runs/-on-GCS-FUSE
        # entry: no os.rename/flock anywhere in this tree, deliberately,
        # since GCS FUSE doesn't support atomic rename reliably).
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fp in sorted(target.rglob("*")):
                # "full"'s target is run_dir itself, which is also where
                # zip_path lives — skip it or the zip would try to include
                # its own (currently being written) bytes.
                if fp.is_file() and fp != zip_path:
                    zf.write(fp, fp.relative_to(target.parent))
        return zip_path.stat().st_size

    loop = asyncio.get_event_loop()
    try:
        size = await loop.run_in_executor(None, _build_and_save)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Zip generation failed: {exc}") from exc

    return JSONResponse({"filename": zip_name, "size": size})


@app.get("/runs/{run_id}/download/{folder_type}")
async def download_run_folder(run_id: str, folder_type: str):
    """Serve the pre-generated .zip for the output-code, skills, kiro-powers,
    openspec, or entire run folder.

    The zip must be created first via POST /runs/{run_id}/zip/{folder_type}.
    folder_type: "output"   → translated source code
                 "skills"   → Claude Code skills folder
                 "kiro"     → Kiro.dev Powers folder (includes hidden .kiro/ directories)
                 "openspec" → OpenSpec (github.com/Fission-AI/OpenSpec) folder
                 "full"     → everything in runs/{run_id}/ — every artifact,
                              report, and generated file
    """
    if folder_type not in ("output", "skills", "kiro", "openspec", "full"):
        raise HTTPException(
            status_code=400,
            detail="folder_type must be 'output', 'skills', 'kiro', 'openspec', or 'full'",
        )

    run = _get_run(run_id)
    run_dir = run.orchestrator.run_dir
    _target, _reports_dir, zip_path = _resolve_zip_target(run_dir, run_id, folder_type)

    if not zip_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Zip not yet built — use the Generate button first.",
        )

    return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)


@app.get("/runs/{run_id}/export/openapi")
async def export_openapi(run_id: str):
    """Generate and serve OpenAPI 3.1 YAML from feature_specs.json.

    Requires the FEATURE_SPECIFIER phase to have completed.
    API-bearing seams populate paths; all seams contribute components/schemas.
    """
    from micro_cosmos.tools.feature_spec_tools import export_openapi as _export_openapi

    run_dir = _get_run(run_id).orchestrator.run_dir
    try:
        yaml_text = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _export_openapi(str(run_dir))
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OpenAPI generation failed: {exc}") from exc

    return StreamingResponse(
        io.BytesIO(yaml_text.encode()),
        media_type="application/yaml",
        headers={"Content-Disposition": 'attachment; filename="openapi.yaml"'},
    )


@app.get("/runs/{run_id}/export/jira")
async def export_jira(run_id: str, project_key: str = "ALX"):
    """Generate and serve Jira bulk-import JSON from feature_specs.json.

    Compatible with POST /rest/api/3/issue/bulk (Jira Server 8+ and Cloud).
    Work streams map to Epics; seams map to Stories.

    Query param: project_key — Jira project key (default: ALX).
    """
    from micro_cosmos.tools.feature_spec_tools import export_jira as _export_jira

    run_dir = _get_run(run_id).orchestrator.run_dir
    try:
        payload = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _export_jira(str(run_dir), project_key.upper())
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Jira export generation failed: {exc}") from exc

    json_bytes = json.dumps(payload, indent=2).encode()
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="jira_bulk_import.json"'},
    )


@app.get("/runs/{run_id}/seams")
async def seam_findings(run_id: str):
    """Seam analysis — returns seam.json if produced, else falls back to live _detect_seams."""
    orch = _get_run(run_id).orchestrator
    seam = orch.load_artifact("seam")
    if seam is not None:
        return JSONResponse(seam)
    raw = orch.load_artifact("ir_graph")
    if isinstance(raw, str):
        raw = _extract_json(raw)
    if not isinstance(raw, dict) or "nodes" not in raw:
        raise HTTPException(status_code=404, detail="IR not yet available")
    try:
        return JSONResponse(_detect_seams(raw))
    except Exception as exc:
        diagnostics.log.exception("seam_findings failed for run %s", run_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/runs/{run_id}/chat")
async def run_chat(run_id: str, request: Request):
    """Q&A chatbot grounded in the run's artifacts with CoT reasoning and multi-turn history.

    Body: {"question": "…", "history": [...], "k": 12}  (history and k are optional)
    history: [{role: "user"|"assistant", content: "…"}, …]  — prior conversation turns

    Response: {"answer": "…", "citations": […], "mode": "generative"|"extractive",
               "steps": [{type, …}, …]}

    steps exposes the retrieval trace (multi-pass queries, chunk counts, artifact kinds)
    and a context summary so the UI can render a collapsible CoT reasoning panel.

    The index is built lazily into runs/<run_id>/vectors/ on first call (covers all
    four pipeline phases + gate decisions) and reused on subsequent calls.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="'question' field is required")

    k = int(body.get("k", get_settings().retrieval_top_k))
    history: list[dict] = body.get("history") or []
    if not isinstance(history, list):
        history = []

    # Resolve run directory: prefer active run, fall back to disk
    run_dir: Path | None = None
    if run_id in RUNS:
        run_dir = RUNS[run_id].orchestrator.run_dir
    else:
        candidate = Path(get_settings().runs_dir) / run_id
        if candidate.is_dir():
            run_dir = candidate

    if run_dir is None or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")

    loop = asyncio.get_event_loop()
    try:
        from micro_cosmos.retrieval.chat import answer as _chat_answer

        result = await loop.run_in_executor(
            None, lambda: _chat_answer(run_dir, question, k=k, history=history)
        )
        return JSONResponse(result)
    except Exception as exc:
        diagnostics.log.exception("chat endpoint failed for run %s", run_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "active_runs": len(RUNS)}


def _example_record(entry: Path) -> dict:
    """One example card, including which family it belongs to and what it may target."""
    from micro_cosmos.etl.catalog import classify_example
    from micro_cosmos.tools.observer_tools import detect_all_langs

    langs = detect_all_langs(str(entry))
    subfolders = []
    if entry.is_dir():
        for sub in sorted(entry.iterdir()):
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            sub_langs = detect_all_langs(str(sub))
            if sub_langs:
                subfolders.append({"name": sub.name, "path": str(sub), "langs": sub_langs})
    record = {
        "name": entry.name,
        "path": str(entry),
        "langs": langs,
        "subfolders": subfolders,
        "description": _read_readme_description(entry),
    }
    record.update(classify_example(entry))
    return record


def _read_readme_description(entry: Path) -> str:
    for name in ("README.md", "ARCHITECTURE.md"):
        candidate = entry / name
        if not candidate.exists():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                clean = line.strip().lstrip("#").strip()
                if clean and not clean.startswith("!") and not clean.startswith("["):
                    return clean[:120]
        except Exception:
            pass
    return ""


@app.get("/", response_class=HTMLResponse)
async def demo_page(request: Request):
    from micro_cosmos.etl.catalog import FAMILY_LABELS

    examples_dir = Path("examples")
    examples = []
    if examples_dir.is_dir():
        for entry in sorted(examples_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            examples.append(_example_record(entry))
    example_groups = [
        {
            **FAMILY_LABELS[family_id],
            "examples": [ex for ex in examples if ex["family"] == family_id],
        }
        for family_id in ("etl", "application")
    ]
    return TEMPLATES.TemplateResponse(request, "demo.html", {
        "examples": examples,
        "example_groups": example_groups,
        # Follows the global SKIP_LLM setting (Settings.skip_llm defaults to
        # True) — also governs the ASK tab / embeddings, not just this
        # toggle. NOTE: the Cloud Run deploy explicitly passes SKIP_LLM=false
        # to protect the production LLM pipeline, so this toggle defaults to
        # LLM there, not Deterministic — only docker-compose/bare-settings
        # environments actually default to Deterministic. See settings.py.
        "skip_llm_default": get_settings().skip_llm,
    })


@app.get("/demo/detect-lang")
async def demo_detect_lang(path: str):
    from micro_cosmos.tools.observer_tools import detect_all_langs
    return JSONResponse({"path": path, "langs": detect_all_langs(path)})


def _extract_zip_to_examples(content: bytes, safe_name: str) -> dict:
    """Extract zip bytes into examples/<safe_name>[_N], return demo-picker card data.

    Shared by /demo/upload and /demo/fetch-github — both end up with zip bytes in
    memory and need the same extraction/validation/card-building logic.
    """
    import io
    import shutil
    import zipfile

    MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB — zip-bomb guard

    examples_dir = Path("examples")
    examples_dir.mkdir(exist_ok=True)

    dest = examples_dir / safe_name
    base = safe_name
    counter = 1
    while dest.exists():
        dest = examples_dir / f"{base}_{counter}"
        counter += 1

    # ── Extract safely ────────────────────────────────────────────────────────
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = [n for n in zf.namelist() if n not in ("/", "")]

            total_uncompressed = sum(zf.getinfo(n).file_size for n in names)
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Archive too large once extracted — maximum is 500 MB uncompressed.",
                )

            # Detect a single common root prefix (e.g. GitHub "project-main/" zips)
            common_root: str | None = None
            if names:
                first_root = names[0].split("/")[0]
                if all(n == first_root + "/" or n.startswith(first_root + "/") for n in names):
                    common_root = first_root

            for member in names:
                # Derive relative path, stripping the common root if present
                rel = member
                if common_root:
                    if rel == common_root + "/":
                        continue
                    rel = rel[len(common_root) + 1:]
                if not rel:
                    continue

                # Guard against path traversal
                target = dest / Path(rel)
                try:
                    target.relative_to(dest)
                except ValueError:
                    continue

                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member))

    except zipfile.BadZipFile:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Invalid or corrupt zip file.")
    except HTTPException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")

    # ── Build card data ───────────────────────────────────────────────────────
    record = _example_record(dest)
    record["description"] = record.get("description") or ""
    return record


@app.post("/demo/upload")
async def demo_upload_example(file: UploadFile = File(...)):
    """Accept a .zip upload, extract it to examples/, return the new card data."""
    import re

    # ── Validate ──────────────────────────────────────────────────────────────
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted.")

    MAX_BYTES = 200 * 1024 * 1024  # 200 MB
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large — maximum is 200 MB.")

    # ── Derive a safe destination name ────────────────────────────────────────
    stem = Path(file.filename).stem
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", stem).strip("_") or "uploaded"

    return JSONResponse(_extract_zip_to_examples(content, safe_name))


@app.post("/demo/fetch-github")
async def demo_fetch_github(github_url: str = Form(...)):
    """Download a public GitHub repo as a zip via codeload.github.com and extract it to examples/.

    Only github.com URLs are accepted — the codeload/API hosts are built server-side from the
    parsed owner/repo, never taken from client input, so the outbound host is never
    attacker-controlled (closes off arbitrary-host SSRF).
    """
    import re
    import urllib.error
    import urllib.request
    from urllib.parse import urlsplit

    MAX_BYTES = 200 * 1024 * 1024  # 200 MB, same cap as /demo/upload
    TIMEOUT_SECONDS = 30

    parsed = urlsplit(github_url.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() not in ("github.com", "www.github.com"):
        raise HTTPException(
            status_code=400,
            detail="Enter a GitHub repository URL, e.g. https://github.com/owner/repo",
        )

    match = re.match(r"^/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/tree/([\w./-]+))?/?$", parsed.path)
    if not match:
        raise HTTPException(
            status_code=400,
            detail="Enter a GitHub repository URL, e.g. https://github.com/owner/repo",
        )
    owner, repo, ref = match.group(1), match.group(2), match.group(3)

    def _fetch_default_branch() -> str:
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "micro-cosmos-demo", "Accept": "application/vnd.github+json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["default_branch"]
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise HTTPException(
                    status_code=404, detail=f"Repository {owner}/{repo} not found (or private)."
                )
            raise HTTPException(
                status_code=502, detail=f"GitHub API error while resolving default branch: {exc.code}"
            )
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach GitHub: {exc.reason}")
        except (KeyError, json.JSONDecodeError):
            raise HTTPException(status_code=502, detail="Unexpected response from GitHub API.")

    def _download_zip(resolved_ref: str) -> bytes:
        zip_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{resolved_ref}"
        req = urllib.request.Request(zip_url, headers={"User-Agent": "micro-cosmos-demo"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                chunks = []
                total = 0
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="Repository archive too large — maximum is 200 MB.",
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Branch/ref '{resolved_ref}' not found for {owner}/{repo}.",
                )
            raise HTTPException(
                status_code=502, detail=f"GitHub returned an error downloading the archive: {exc.code}"
            )
        except urllib.error.URLError as exc:
            raise HTTPException(
                status_code=502, detail=f"Could not download the repository archive: {exc.reason}"
            )

    def _fetch_all() -> tuple[bytes, str]:
        resolved_ref = ref or _fetch_default_branch()
        content = _download_zip(resolved_ref)
        return content, resolved_ref

    try:
        content, _resolved_ref = await asyncio.to_thread(_fetch_all)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch repository: {exc}")

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", f"{owner}_{repo}").strip("_") or "github_repo"
    result = _extract_zip_to_examples(content, safe_name)
    result["github_url"] = f"https://github.com/{owner}/{repo}"
    return JSONResponse(result)
