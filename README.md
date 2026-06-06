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
`analyze_trace` endpoint through `@gradio/client`. Both models run on the Space
GPU through ZeroGPU: a quick `Qwen/Qwen3.5-9B` pass by default, and the larger
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` for deeper analysis. A verified
deterministic codebook analyzer is the always-available recovery path and needs
no model or GPU.

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

- `Qwen3.5 9B — quick analysis`: default model pass on the Space GPU.
- `NVIDIA Nemotron 3 Nano 30B-A3B — deeper analysis`: the larger model on the
  Space GPU for a richer memo.
- `Rule-based — instant, no model`: local codebook analyzer, no model or GPU.

If a model fails to load or returns invalid JSON, the report records the reason
in model notes and returns the deterministic analysis instead of failing the
whole Space.

The model-backed analysis runs under `@spaces.GPU(size="xlarge")` so the weights
load on Hugging Face ZeroGPU hardware; `Qwen/Qwen3.5-9B` and
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` are loaded with `transformers` and
cached across requests. The rule-based engine runs on CPU and never requests a
GPU slot, so it returns instantly.

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
before uploading or sharing publicly. The app defaults to basic regex redaction
and exports only a redacted narrative text file.
