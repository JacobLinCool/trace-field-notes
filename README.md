---
title: Trace Field Notes
colorFrom: green
colorTo: gray
sdk: gradio
sdk_version: 6.16.0
app_file: app.py
pinned: false
license: mit
---

# Trace Field Notes

Trace Field Notes turns coding-agent session logs into qualitative field reports.

Upload a Codex, Claude Code, or Pi Agent JSONL trace. The app ignores raw tool
telemetry by default and analyzes only the agent's visible narrative messages:
what it planned, where it got stuck, how it detoured, how it recovered, and how
it claimed completion.

Built for the Build Small Hackathon. The frontend is a custom React field-notebook
UI (a trail map of the session) served by `gradio.Server`; it calls the Python
`analyze_trace` endpoint through `@gradio/client`. Both analysis models run on the
Space GPU through ZeroGPU: a quick `openbmb/MiniCPM5-1B` pass by default, and the
larger `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` for deeper analysis. Redaction
adds a PII pass with `openai/privacy-filter`. A verified deterministic codebook
analyzer is the always-available recovery path and needs no model or GPU.

## Architecture

- `app.py` — a `gradio.Server` (FastAPI) app. It serves `frontend/index.html`,
  mounts `frontend/static/`, exposes `@server.api("analyze_trace")` (queued, with
  `gradio_client` compatibility), and an `/agents.md` instructions endpoint.
- `frontend/` — the designer's React app (in-browser Babel, no build step):
  `field_report.css` (the design system), `data.js` (codebook + tone labels),
  `components.jsx` (atoms + trail map + report sections), `app.jsx` (shell +
  upload, wired to the backend).
- `view_model.py` — adapts an `AnalysisResult` into the JSON shape the frontend
  renders (synthesizes the whole-session `verdict`, `captured`, `duration_total`).
- `analyzer.py` / `parser.py` / `redaction.py` / `schemas.py` — the deterministic
  pipeline. `model_runtime.py` — the optional small-model assist on ZeroGPU.
  `privacy_filter.py` — the optional `openai/privacy-filter` PII redaction pass.
  `profiling.py` — logging + per-request stage timing and resource probes.

## Run Locally

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Test

```bash
python3.11 -m unittest discover -s tests
```

## Analysis Engines

- `MiniCPM5 1B — quick analysis`: default model pass on the Space GPU.
- `NVIDIA Nemotron 3 Nano 30B-A3B — deeper analysis`: the larger model on the
  Space GPU for a richer memo.
- `Rule-based — instant, no model`: local codebook analyzer, no model or GPU.

If a model fails to load or returns invalid JSON, the report records the reason
in model notes and returns the deterministic analysis instead of failing the
whole Space.

The model-backed analysis runs under `@spaces.GPU(size="xlarge")` so the weights
load on Hugging Face ZeroGPU hardware; `openbmb/MiniCPM5-1B` and
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` are loaded with `transformers` and
cached across requests. The deterministic codebook analysis itself runs on CPU;
only the model assist and the `openai/privacy-filter` redaction pass use the GPU,
and both fall back gracefully (deterministic analysis / regex-only redaction)
when no GPU model is available.

## Execution modes

Each `analyze_trace` call takes an `execution_mode`:

- `zerogpu` (default): the model passes run inside `@spaces.GPU` on the Space GPU.
- `cpu`: the model passes run on the Space (or local) CPU with **no GPU quota** —
  slower, but it still works when ZeroGPU quota is exhausted. The frontend exposes
  this as a **Run on** choice so users without quota can still use the app.

Model loading is device-aware (CUDA → Apple MPS → CPU), so the app also runs
locally for development; on a Mac the small models run on MPS, and the
deterministic engine needs no model at all. Because of the slower paths, the
frontend streams real progress — current stage, % complete, messages processed,
elapsed time, and a best-effort ETA — so a long run never looks stuck.

## Logging & profiling

The pipeline writes diagnostics to the standard logger (never the UI): per-request
message count, per-stage timing, total time, model load/inference time with the
device used, and a resource snapshot (process RSS, system memory, CPU, and
GPU/MPS memory). Set the level with `TFN_LOG_LEVEL` (default `INFO`; use `DEBUG`
for per-stage detail). Example summary line:

```
analyze[zerogpu/minicpm] done in 19.4s | messages=4 redactions=2 episodes=1
  | stages: extract=0ms, redact=9503ms, chart=4ms, classify=0ms, model_assist=9918ms
  | rss=2180MB sysmem=68% mps=4732MB
```

## Agent Session Locations

```bash
# Codex
ls ~/.codex/sessions

# Claude Code
ls ~/.claude/projects

# Pi Agent
ls ~/.pi/agent/sessions
```

## Privacy

Agent traces can contain prompts, tool inputs, command outputs, local file paths,
screenshots, secrets, private source code, and personal data. Review and redact
before uploading or sharing publicly. Redaction defaults to regex patterns plus a
model pass (`openai/privacy-filter`) that flags names, contacts, and other
personal data on the Space GPU; the regex pass is the always-available fallback
when the model is not loaded. The app exports only a redacted narrative text file.
