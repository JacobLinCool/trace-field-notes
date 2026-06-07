"""Trace Field Notes — gradio.Server backend behind the designer's React frontend.

The custom frontend (``frontend/``) is served as static files; it talks to the
``analyze_trace`` endpoint below through ``@gradio/client``. The endpoint runs the
deterministic analyzer (and the optional small-model assist on ZeroGPU) and
returns the frontend-ready view model.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import spaces
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from gradio import Server
from gradio.data_classes import FileData

from analyzer import apply_model_analysis, stream_deterministic_analysis
from parser import TraceParseError
from profiling import Profiler, get_logger
from view_model import build_view_model

logger = get_logger()


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
- `redact_secrets` (bool): regex + AI (`openai/privacy-filter`) PII redaction before analysis
- `analysis_engine` (str): `minicpm` | `nemotron` | `deterministic`
- `execution_mode` (str): `zerogpu` (default, uses the Space GPU) | `cpu` (no GPU quota, slower)

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
def _model_analysis_gpu(*, engine, numbered_narrative, agent_type, codebook_hint):
    """Run the primary model analysis inside a ZeroGPU allocation."""

    from model_runtime import run_model_analysis

    return run_model_analysis(
        engine=engine,
        numbered_narrative=numbered_narrative,
        agent_type=agent_type,
        codebook_hint=codebook_hint,
    )


@spaces.GPU(size="xlarge", duration=120)
def _privacy_filter_gpu(texts):
    """Run the openai/privacy-filter PII pass inside a ZeroGPU allocation."""

    from privacy_filter import redact_texts

    return redact_texts(texts)


def _cpu_privacy_filter(texts):
    """Run the openai/privacy-filter PII pass on the local CPU (no GPU quota)."""

    from privacy_filter import redact_texts

    return redact_texts(texts, device="cpu")


def _cpu_model_analysis(*, engine, numbered_narrative, agent_type, codebook_hint):
    """Run the primary model analysis on the local CPU (no GPU quota)."""

    from model_runtime import run_model_analysis

    return run_model_analysis(
        engine=engine,
        numbered_narrative=numbered_narrative,
        agent_type=agent_type,
        codebook_hint=codebook_hint,
        device="cpu",
    )


# Per stage: (frontend checklist index, cumulative %, label). The 6-item
# checklist is: 0 upload, 1 extract, 2 redact, 3 chart, 4 classify, 5 synthesize.
# Indices below are "rows completed" so the matching row shows as active.
_STAGE_PLAN = {
    "extract": (2, 12, "Extracting narrative messages"),
    "chart": (4, 55, "Charting difficulty episodes"),
    "classify": (5, 62, "Classifying with the codebook"),
    "synthesize": (5, 70, "Synthesizing field notes"),
}

# Redaction streams per-chunk progress; its % ramps across this band.
_REDACT_PCT = (12, 40)


def _progress_event(*, step, pct, label, elapsed, processed=None, total=None):
    """Build one streamed progress payload (with a best-effort ETA)."""

    event = {"step": step, "pct": pct, "stage": label, "elapsed": round(elapsed, 1)}
    if 0 < pct < 100:
        event["eta"] = round(elapsed * (100 - pct) / pct, 1)
    if total is not None:
        event["total"] = total
        event["processed"] = processed if processed is not None else total
    return event


def _stage_event(payload, *, elapsed, message_total):
    """Translate a stream progress payload into a frontend event + running total."""

    stage = payload["stage"]
    if stage == "redact":
        total = payload.get("total") or message_total or 0
        processed = payload.get("processed", total)
        frac = (processed / total) if total else 1.0
        low, high = _REDACT_PCT
        pct = round(low + (high - low) * frac)
        step = 2 if (total and processed < total) else 3
        event = _progress_event(
            step=step,
            pct=pct,
            label="Redacting likely secrets",
            elapsed=elapsed,
            processed=processed,
            total=total or None,
        )
        return event, (total or message_total)

    step, pct, label = _STAGE_PLAN[stage]
    total = payload.get("messages", message_total)
    event = _progress_event(step=step, pct=pct, label=label, elapsed=elapsed, total=total)
    return event, total


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
    analysis_engine: str = "minicpm",
    execution_mode: str = "zerogpu",
) -> dict:
    """Stream real progress, then the frontend view model, for one trace.

    Yields ``{"step", "pct", "stage", "elapsed", "eta", "total"}`` after each
    real pipeline stage (so the UI shows true progress), then a final
    ``{"step": 6, "pct": 100, "result": <view model>}``.

    ``execution_mode`` is ``zerogpu`` (default; models run inside ``@spaces.GPU``)
    or ``cpu`` (models run on the Space/local CPU, no GPU quota — slower).
    """

    path, orig_name = _file_fields(trace_file)
    if not path:
        raise ValueError("No uploaded file was received.")

    use_cpu = execution_mode == "cpu"
    redactor = _cpu_privacy_filter if use_cpu else _privacy_filter_gpu
    analysis_runner = _cpu_model_analysis if use_cpu else _model_analysis_gpu

    prof = Profiler(f"analyze[{execution_mode}/{analysis_engine}]")
    logger.info(
        "analyze_trace start: file=%r engine=%s mode=%s redact=%s",
        orig_name,
        analysis_engine,
        execution_mode,
        redact_secrets,
    )

    result = None
    narrative = ""
    messages = []
    message_total = None
    try:
        for kind, payload in stream_deterministic_analysis(
            path,
            include_user_context=include_user_context,
            redact_secrets=redact_secrets,
            ignore_tool_calls=True,
            model_redact=redactor,
            profiler=prof,
            stream_redact_progress=use_cpu,
        ):
            if kind == "progress":
                event, message_total = _stage_event(
                    payload, elapsed=prof.elapsed(), message_total=message_total
                )
                yield event
            elif kind == "result":
                result, narrative, messages = payload
    except TraceParseError as exc:
        raise ValueError(str(exc)) from exc

    if analysis_engine != "deterministic":
        yield _progress_event(
            step=5,
            pct=78,
            label=f"Reading the trace with {analysis_engine}",
            elapsed=prof.elapsed(),
            total=message_total,
        )
        analysis_started = time.perf_counter()
        apply_model_analysis(result, messages, analysis_engine, run=analysis_runner)
        prof.record("model_analysis", time.perf_counter() - analysis_started)

    if orig_name:
        agent = READABLE_AGENT.get(result.agent_type_guess, "Agent")
        result.trace_title = f"{agent} · {orig_name}"

    view = build_view_model(result, narrative)
    prof.mark(engine=result.engine, mode=execution_mode)
    prof.summary()
    yield {
        "step": 6,
        "pct": 100,
        "stage": "Field notes ready",
        "elapsed": round(prof.elapsed(), 1),
        "total": message_total,
        "processed": message_total,
        "result": view,
    }


if __name__ == "__main__":
    server.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", os.getenv("GRADIO_SERVER_PORT", "7860"))),
        show_error=True,
    )
