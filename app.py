"""Gradio entrypoint for the Trace Field Notes Hugging Face Space."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Optional

import gradio as gr
import spaces

from analyzer import analyze_trace_file
from model_runtime import MODEL_CHOICES
from parser import TraceParseError
from report_renderer import render_report


SPACE_URL = "https://huggingface.co/spaces/build-small-hackathon/trace-field-notes"
DEFAULT_ANALYSIS_ENGINE = "qwen"
SAMPLE_TRACE_PATH = "examples/sample_trace_redacted.jsonl"

PRIVACY_WARNING = (
    "Agent traces can contain prompts, tool inputs, command outputs, local file paths, "
    "screenshots, secrets, private source code, and personal data. Redact before uploading. "
    "This app analyzes only visible agent narrative messages by default and does not need raw tool outputs."
)

HERO_MD = """
**ZeroGPU field report**

# Trace Field Notes

Map where a coding agent got stuck, changed route, recovered, and claimed success.
"""

SESSION_PATHS_MD = """
### Session Logs

| Agent | Local session directory |
|---|---|
| Codex | `~/.codex/sessions` |
| Claude Code | `~/.claude/projects` |
| Pi Agent | `~/.pi/agent/sessions` |
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
  --field-border: rgba(148, 163, 184, 0.28);
  --field-ink: #f8fafc;
  --field-muted: #94a3b8;
  --field-panel: rgba(15, 23, 42, 0.74);
  --field-panel-strong: rgba(15, 23, 42, 0.92);
  --field-accent: #2f8a69;
  --field-accent-strong: #23785d;
}
.gradio-container {
  max-width: 1220px !important;
  color: var(--field-ink);
}
.hero {
  border: 1px solid var(--field-border);
  border-radius: 8px;
  padding: 18px 20px;
  background: linear-gradient(135deg, rgba(47, 138, 105, 0.18), rgba(15, 23, 42, 0.3));
}
.hero h1 {
  margin: 0;
  font-size: 34px;
  line-height: 1.08;
}
.hero p {
  max-width: 760px;
  margin: 10px 0 0;
  color: var(--field-muted);
  font-size: 15px;
}
.hero strong {
  margin-bottom: 8px;
  color: #7dd3fc;
  font: 700 12px/1.2 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  text-transform: uppercase;
  letter-spacing: 0;
}
.privacy-callout {
  margin: 12px 0 16px;
  border-left: 3px solid #f59e0b;
  padding: 10px 12px;
  color: #dbe4ef;
  background: rgba(245, 158, 11, 0.08);
  border-radius: 0 6px 6px 0;
}
.trace-panel {
  border: 1px solid var(--field-border);
  border-radius: 8px;
  padding: 16px;
  background: var(--field-panel);
}
.guide-panel {
  border: 1px solid var(--field-border);
  border-radius: 8px;
  padding: 16px;
  background: var(--field-panel);
}
.guide-panel table {
  width: 100%;
}
.action-row button {
  min-height: 42px;
}
button.primary {
  background: var(--field-accent) !important;
  border-color: var(--field-accent) !important;
}
button.primary:hover {
  background: var(--field-accent-strong) !important;
}
.download-row {
  align-items: stretch;
}
.result-tabs {
  margin-top: 14px;
}
textarea, input {
  border-radius: 6px !important;
}
"""


def _analyze_trace_impl(
    trace_file: Any,
    include_user_context: bool = True,
    redact_secrets: bool = True,
    ignore_tool_calls: bool = True,
    report_style: str = "field_notes",
    analysis_engine: str = DEFAULT_ANALYSIS_ENGINE,
    oauth_token: Optional[gr.OAuthToken] = None,
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
            analysis_engine=analysis_engine,
            hf_token=oauth_token.token if oauth_token else None,
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


@spaces.GPU(duration=90)
def analyze_trace(
    trace_file: Any,
    include_user_context: bool = True,
    redact_secrets: bool = True,
    ignore_tool_calls: bool = True,
    report_style: str = "field_notes",
    analysis_engine: str = DEFAULT_ANALYSIS_ENGINE,
    oauth_token: Optional[gr.OAuthToken] = None,
) -> tuple[str, dict[str, Any], str, str, str]:
    """ZeroGPU-visible Gradio endpoint."""

    return _analyze_trace_impl(
        trace_file=trace_file,
        include_user_context=include_user_context,
        redact_secrets=redact_secrets,
        ignore_tool_calls=ignore_tool_calls,
        report_style=report_style,
        analysis_engine=analysis_engine,
        oauth_token=oauth_token,
    )


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


def load_sample_trace() -> tuple[str, bool, bool, bool, str, str]:
    return SAMPLE_TRACE_PATH, True, True, True, "field_notes", DEFAULT_ANALYSIS_ENGINE


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
    gr.Markdown(HERO_MD, elem_classes=["hero"])
    gr.Markdown(PRIVACY_WARNING, elem_classes=["privacy-callout"])

    with gr.Row(equal_height=False):
        with gr.Column(scale=3, elem_classes=["trace-panel"]):
            gr.Markdown("### Trace Input")
            trace_input = gr.File(
                label="Agent session log",
                file_types=[".jsonl", ".json", ".txt", ".log"],
                type="filepath",
            )
            with gr.Row():
                include_user_context = gr.Checkbox(
                    value=True,
                    label="Include user context",
                )
                redact_secrets = gr.Checkbox(
                    value=True,
                    label="Redact likely secrets",
                )
            ignore_tool_calls = gr.Checkbox(
                value=True,
                label="Ignore tool contents",
                interactive=False,
            )
            report_style = gr.Radio(
                choices=[("Field notes", "field_notes")],
                value="field_notes",
                label="Report style",
                interactive=False,
                visible=False,
            )
            analysis_engine = gr.Radio(
                choices=[
                    (str(choice["label"]), key)
                    for key, choice in MODEL_CHOICES.items()
                ],
                value=DEFAULT_ANALYSIS_ENGINE,
                label="Analysis engine",
            )
            with gr.Row():
                gr.LoginButton(
                    value="Sign in for model assist",
                    logout_value="Signed in as {}",
                    size="sm",
                )
            gr.Markdown(
                "Model-assisted modes use your signed-in Hugging Face OAuth token with the `inference-api` scope. "
                "The deterministic engine does not require sign-in."
            )
            with gr.Row(elem_classes=["action-row"]):
                analyze_button = gr.Button("Analyze My Trace", variant="primary")
                sample_button = gr.Button("Use Sample Trace", variant="secondary")
        with gr.Column(scale=2, elem_classes=["guide-panel"]):
            gr.Markdown(SESSION_PATHS_MD)
            with gr.Accordion("Agent-callable prompt", open=False):
                gr.Textbox(
                    value=AGENT_PROMPT,
                    label="Prompt for Codex or Claude Code",
                    lines=9,
                    interactive=False,
                    show_copy_button=True,
                )

    sample_button.click(
        load_sample_trace,
        inputs=None,
        outputs=[
            trace_input,
            include_user_context,
            redact_secrets,
            ignore_tool_calls,
            report_style,
            analysis_engine,
        ],
    )

    with gr.Tabs(elem_classes=["result-tabs"]):
        with gr.Tab("Field Report"):
            report_output = gr.Markdown(label="Field Report")
        with gr.Tab("Episodes JSON"):
            episode_json = gr.JSON(label="Structured Episode JSON")
        with gr.Tab("Downloads"):
            with gr.Row(elem_classes=["download-row"]):
                redacted_download = gr.File(label="Redacted Narrative")
                report_download = gr.File(label="Markdown Report")
                json_download = gr.File(label="Structured JSON")

    analyze_button.click(
        analyze_trace,
        inputs=[
            trace_input,
            include_user_context,
            redact_secrets,
            ignore_tool_calls,
            report_style,
            analysis_engine,
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
