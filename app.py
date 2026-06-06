"""Gradio entrypoint for the Trace Field Notes Hugging Face Space."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import gradio as gr

from analyzer import analyze_trace_file
from parser import TraceParseError
from report_renderer import render_report


SPACE_URL = "https://huggingface.co/spaces/build-small-hackathon/trace-field-notes"

PRIVACY_WARNING = (
    "Agent traces can contain prompts, tool inputs, command outputs, local file paths, "
    "screenshots, secrets, private source code, and personal data. Redact before uploading. "
    "This app analyzes only visible agent narrative messages by default and does not need raw tool outputs."
)

HERO_MD = f"""
# Trace Field Notes

See how your coding agent got stuck, detoured, recovered, and claimed success.

Upload a Codex, Claude Code, or Pi Agent session log. The app extracts visible narrative messages, classifies difficulty episodes, and turns the session into a qualitative field report.

> {PRIVACY_WARNING}
"""

SESSION_PATHS_MD = """
## Find Your Session Log

| Agent | Local session directory |
|---|---|
| Codex | `~/.codex/sessions` |
| Claude Code | `~/.claude/projects` |
| Pi Agent | `~/.pi/agent/sessions` |

```bash
# Codex
ls ~/.codex/sessions

# Claude Code
ls ~/.claude/projects

# Pi Agent
ls ~/.pi/agent/sessions
```
"""

AGENT_PROMPT = f"""Use this Space as a tool.
1. Read: {SPACE_URL}/agents.md
2. Find my latest local agent session log:
   - Codex: ~/.codex/sessions
   - Claude Code: ~/.claude/projects
   - Pi Agent: ~/.pi/agent/sessions
3. Review and redact secrets or private code before upload.
4. Upload the JSONL to the Space.
5. Ask for narrative difficulty analysis.
6. Return the report. Do not publish the raw trace.
"""

CUSTOM_CSS = """
:root {
  --field-border: #d7d0c2;
  --field-ink: #202124;
  --field-muted: #605b52;
  --field-paper: #fbfaf7;
  --field-accent: #326b59;
}
.gradio-container {
  max-width: 1180px !important;
  color: var(--field-ink);
}
.trace-panel {
  border: 1px solid var(--field-border);
  border-radius: 8px;
  padding: 14px;
  background: var(--field-paper);
}
button.primary {
  background: var(--field-accent) !important;
  border-color: var(--field-accent) !important;
}
textarea, input {
  border-radius: 6px !important;
}
"""


def analyze_trace(
    trace_file: Any,
    include_user_context: bool = True,
    redact_secrets: bool = True,
    ignore_tool_calls: bool = True,
    report_style: str = "field_notes",
) -> tuple[str, dict[str, Any], str, str, str]:
    """Gradio-callable analysis endpoint."""

    if trace_file is None:
        raise gr.Error("Upload a .jsonl, .json, .txt, or .log trace file first.")

    path = uploaded_path(trace_file)
    try:
        result, redacted_narrative = analyze_trace_file(
            path,
            include_user_context=include_user_context,
            redact_secrets=redact_secrets,
            ignore_tool_calls=ignore_tool_calls,
            report_style=report_style,
        )
    except TraceParseError as exc:
        raise gr.Error(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - surfaced to the Space UI.
        raise gr.Error(f"Analysis failed: {exc}") from exc

    report_markdown = render_report(result)
    result_json = result.to_dict()
    redacted_file = write_temp_artifact("trace-field-notes-redacted-", ".md", redacted_narrative)
    report_file = write_temp_artifact("trace-field-notes-report-", ".md", report_markdown)
    json_file = write_temp_artifact(
        "trace-field-notes-episodes-",
        ".json",
        json.dumps(result_json, indent=2, ensure_ascii=False) + "\n",
    )
    return report_markdown, result_json, redacted_file, report_file, json_file


def uploaded_path(trace_file: Any) -> Path:
    if isinstance(trace_file, (str, Path)):
        return Path(trace_file)
    name = getattr(trace_file, "name", None)
    if name:
        return Path(name)
    path = getattr(trace_file, "path", None)
    if path:
        return Path(path)
    raise gr.Error("Could not resolve the uploaded file path.")


def write_temp_artifact(prefix: str, suffix: str, content: str) -> str:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix=prefix,
        suffix=suffix,
        delete=False,
    ) as handle:
        handle.write(content)
        return handle.name


with gr.Blocks(
    title="Trace Field Notes",
    css=CUSTOM_CSS,
    theme=gr.themes.Base(
        primary_hue="green",
        neutral_hue="stone",
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "ui-monospace", "monospace"],
    ),
) as demo:
    gr.Markdown(HERO_MD)

    with gr.Row(equal_height=False):
        with gr.Column(scale=3, elem_classes=["trace-panel"]):
            trace_input = gr.File(
                label="Upload Agent Session Log",
                file_types=[".jsonl", ".json", ".txt", ".log"],
                type="filepath",
            )
            with gr.Row():
                include_user_context = gr.Checkbox(
                    value=True,
                    label="Include user prompts as context",
                )
                redact_secrets = gr.Checkbox(
                    value=True,
                    label="Redact likely secrets before analysis",
                )
            ignore_tool_calls = gr.Checkbox(
                value=True,
                label="Ignore tool call contents",
                interactive=False,
            )
            report_style = gr.Radio(
                choices=[("Field notes", "field_notes")],
                value="field_notes",
                label="Report style",
                interactive=False,
            )
            analyze_button = gr.Button("Analyze My Trace", variant="primary")
        with gr.Column(scale=2):
            gr.Markdown(SESSION_PATHS_MD)

    with gr.Accordion("Agent-callable prompt", open=False):
        gr.Textbox(
            value=AGENT_PROMPT,
            label="Prompt for Codex or Claude Code",
            lines=9,
            interactive=False,
            show_copy_button=True,
        )

    gr.Examples(
        examples=[["examples/sample_trace_redacted.jsonl", True, True, True, "field_notes"]],
        inputs=[trace_input, include_user_context, redact_secrets, ignore_tool_calls, report_style],
        label="Try a redacted sample trace",
    )

    report_output = gr.Markdown(label="Field Report")
    with gr.Row():
        episode_json = gr.JSON(label="Structured Episode JSON")
    with gr.Row():
        redacted_download = gr.File(label="Download Redacted Narrative")
        report_download = gr.File(label="Download Markdown Report")
        json_download = gr.File(label="Download Structured JSON")

    analyze_button.click(
        analyze_trace,
        inputs=[
            trace_input,
            include_user_context,
            redact_secrets,
            ignore_tool_calls,
            report_style,
        ],
        outputs=[
            report_output,
            episode_json,
            redacted_download,
            report_download,
            json_download,
        ],
        api_name="analyze_trace",
    )


if __name__ == "__main__":
    demo.launch()
