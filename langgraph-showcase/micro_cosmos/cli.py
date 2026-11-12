"""Micro-Cosmos CLI — `micro-cosmos serve` boots the web UI; `micro-cosmos run` runs
the pipeline non-interactively against a source path."""

from __future__ import annotations

import asyncio
import json

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel

from micro_cosmos.orchestration import MicroCosmosOrchestrator
from micro_cosmos.orchestration.driver import run_full_pipeline
from micro_cosmos.settings import get_settings

app = typer.Typer(help="Micro-Cosmos — neurosymbolic code modernisation pipeline.")
console = Console()


@app.command()
def serve(
    host: str = typer.Option(None, help="Host to bind (defaults to settings)"),
    port: int = typer.Option(None, help="Port to bind (defaults to settings)"),
):
    """Boot the web UI."""
    s = get_settings()
    h = host or s.web_host
    p = port or s.web_port
    console.print(Panel.fit(
        f"Micro-Cosmos web UI starting on http://{h}:{p}\n"
        f"LLM: {s.llm_base_url}\n"
        f"Model: {s.model_reasoning}",
        title="micro-cosmos serve",
    ))
    uvicorn.run("micro_cosmos.web.app:app", host=h, port=p, reload=False)


@app.command()
def run(
    source: str = typer.Argument(..., help="Source estate path"),
    source_lang: str = typer.Option("", "--source-lang", "-s", help="Source language (auto-detected if omitted)"),
    target_lang: str = typer.Option("", "--target-lang", "-t", help="Target language (e.g. java21, python3, go, rust, kotlin)"),
    auto_approve: bool = typer.Option(
        False, "--auto-approve", help="Auto-approve every gate (CI / demo use only)"
    ),
):
    """Run the pipeline once, non-interactively."""
    if not source_lang:
        from micro_cosmos.tools.observer_tools import detect_source_lang
        source_lang = detect_source_lang(source)
        if source_lang:
            console.print(f"[dim]Auto-detected source language: {source_lang}[/dim]")
        else:
            console.print(
                "[yellow]Could not auto-detect source language. "
                "Pass --source-lang explicitly (e.g. --source-lang python2, java8, go).[/yellow]"
            )
            raise typer.Exit(code=1)
    if not target_lang:
        console.print(
            "[red]--target-lang is required (e.g. --target-lang java21, python3, go, rust, kotlin).[/red]"
        )
        raise typer.Exit(code=1)
    asyncio.run(_run_pipeline_cli(source, source_lang, target_lang, auto_approve))


async def _run_pipeline_cli(
    source: str, source_lang: str, target_lang: str, auto_approve: bool
) -> None:
    import uuid
    run_id = uuid.uuid4().hex[:8]
    orch = MicroCosmosOrchestrator(run_id)

    async def auto_approver() -> None:
        # Poll gate states and auto-approve any that are open
        while True:
            await asyncio.sleep(0.5)
            for gs in orch.gate_state_snapshot():
                if gs["decision"] == "PENDING" and gs["pending_artifact_sha"]:
                    orch.approve_gate(gs["gate_id"], reviewer_name="auto-approver", notes="CI mode")

    tasks = []
    if auto_approve:
        tasks.append(asyncio.create_task(auto_approver()))

    try:
        async for event in run_full_pipeline(orch, source, source_lang, target_lang):
            _pretty_print(event)
    finally:
        for t in tasks:
            t.cancel()


def _pretty_print(event) -> None:
    payload = json.dumps(event.payload, default=str)[:240]
    console.print(f"[bold cyan]{event.kind}[/bold cyan] [yellow]{event.phase.value}[/yellow] {payload}")


@app.command()
def models():
    """List models available on the LM Studio local server."""
    import httpx
    from micro_cosmos.settings import get_settings

    s = get_settings()
    base = s.llm_base_url.rstrip("/")
    try:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {s.llm_api_key}"}, timeout=5)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            console.print("[yellow]No models loaded — load a model in LM Studio and start the server.[/yellow]")
            return
        console.print(f"[bold]Models on {base}:[/bold]")
        for m in data:
            marker = " ← active" if m["id"] in (s.model_reasoning, s.model_fast) else ""
            console.print(f"  {m['id']}{marker}")
        console.print(f"\n[dim]Configured: model_reasoning={s.model_reasoning!r}  model_fast={s.model_fast!r}[/dim]")
        console.print("[dim]Set MODEL_REASONING / MODEL_FAST in .env to match the model ID above.[/dim]")
    except Exception as exc:
        console.print(f"[red]Cannot reach LM Studio at {base}: {exc}[/red]")
        console.print("[dim]Open LM Studio → Developer tab → start the local server.[/dim]")


@app.command()
def version():
    """Print the Micro-Cosmos version."""
    from importlib.metadata import version as get_version

    try:
        console.print(get_version("micro-cosmos"))
    except Exception:
        console.print("0.1.0 (uninstalled)")


if __name__ == "__main__":
    app()
