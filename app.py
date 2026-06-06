"""Trace Field Notes — gradio.Server backend behind the designer's React frontend.

The custom frontend (``frontend/``) is served as static files; it talks to the
``analyze_trace`` endpoint below through ``@gradio/client``. The endpoint runs the
deterministic analyzer (and the optional small-model assist on ZeroGPU) and
returns the frontend-ready view model.
"""

from __future__ import annotations

import os
from pathlib import Path

import spaces
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from gradio import Server
from gradio.data_classes import FileData

from analyzer import apply_model_assist, stream_deterministic_analysis
from parser import TraceParseError
from view_model import build_view_model


HERE = Path(__file__).resolve().parent
FRONTEND = HERE / "frontend"

READABLE_AGENT = {"codex": "Codex", "claude_code": "Claude Code", "pi": "Pi Agent", "unknown": "Agent"}

AGENTS_MD = """# Trace Field Notes — agent instructions

This Space turns a coding-agent session log into a qualitative *field report*:
where the agent got stuck, where it changed route, how it recovered, and how
honestly it claimed success. It reads only the agent's visible narrative
messages and ignores raw tool telemetry.

## How to use it as a tool

1. Find the user's latest local session log:
   - Codex: `~/.codex/sessions`
   - Claude Code: `~/.claude/projects`
   - Pi Agent: `~/.pi/agent/sessions`
2. Review it and redact secrets, tokens, local paths, and private code first.
3. Upload the `.jsonl` (`.json` / `.txt` / `.log` also accepted) and call the
   `analyze_trace` API endpoint.
4. Return the field report to the user. Do not publish the raw trace.

## API

`POST` via the Gradio client, endpoint `/analyze_trace`:

- `trace_file` (file): the session log
- `include_user_context` (bool): include user prompts as framing
- `redact_secrets` (bool): redact likely secrets before analysis
- `analysis_engine` (str): `qwen` | `nemotron` | `deterministic`

Returns a JSON view model: a whole-session `verdict`, per-episode difficulty
`episodes`, and redacted export text.
"""


server = Server(title="Trace Field Notes")
server.mount("/static", StaticFiles(directory=str(FRONTEND / "static")), name="static")


@server.get("/", response_class=HTMLResponse)
def index() -> str:
    return (FRONTEND / "index.html").read_text(encoding="utf-8")


@server.get("/agents.md", response_class=PlainTextResponse)
def agents_md() -> str:
    return AGENTS_MD


@spaces.GPU(size="xlarge", duration=180)
def _model_assist_gpu(*, engine, result, narrative_text):
    """Run the small-model assist inside a ZeroGPU allocation."""

    from model_runtime import run_model_assist

    return run_model_assist(engine=engine, result=result, narrative_text=narrative_text)


# completed-step count for the frontend's 6-item checklist
# (item 0 "uploading" is done once the request reaches us).
_STEP_COUNT = {"extract": 2, "redact": 3, "chart": 4, "classify": 5, "synthesize": 5}


def _file_fields(trace_file: object) -> tuple[str | None, str | None]:
    """The file input may arrive as a FileData model or a plain FileDataDict."""

    if isinstance(trace_file, dict):
        return trace_file.get("path"), trace_file.get("orig_name")
    return getattr(trace_file, "path", None), getattr(trace_file, "orig_name", None)


@server.api(name="analyze_trace")
def analyze_trace(
    trace_file: FileData,
    include_user_context: bool = True,
    redact_secrets: bool = True,
    analysis_engine: str = "qwen",
) -> dict:
    """Stream real progress, then the frontend view model, for one trace.

    Yields ``{"step": n}`` after each real pipeline stage (so the UI checklist
    tracks actual work), then a final ``{"step": 6, "result": <view model>}``.
    """

    path, orig_name = _file_fields(trace_file)
    if not path:
        raise ValueError("No uploaded file was received.")

    result = None
    narrative = ""
    try:
        for kind, payload in stream_deterministic_analysis(
            path,
            include_user_context=include_user_context,
            redact_secrets=redact_secrets,
            ignore_tool_calls=True,
        ):
            if kind == "step":
                yield {"step": _STEP_COUNT[payload]}
            elif kind == "result":
                result, narrative = payload
    except TraceParseError as exc:
        raise ValueError(str(exc)) from exc

    if analysis_engine != "deterministic":
        apply_model_assist(result, narrative, analysis_engine, run=_model_assist_gpu)

    if orig_name:
        agent = READABLE_AGENT.get(result.agent_type_guess, "Agent")
        result.trace_title = f"{agent} · {orig_name}"

    yield {"step": 6, "result": build_view_model(result, narrative)}


if __name__ == "__main__":
    server.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", os.getenv("GRADIO_SERVER_PORT", "7860"))),
        show_error=True,
    )
