import json

from theoretical.llm_utils import strip_json_markdown_fence, escape_markdown_dollar
from theoretical.hypothesis_extraction.phrasing import apply_phrasing_guards
from theoretical.hypothesis_extraction.scanner import Hypothesis


def test_unfenced_text_passes_through_unchanged():
    text = '[{"field_code": "A1", "statement": "x"}]'
    assert strip_json_markdown_fence(text) == text


def test_json_fenced_text_is_stripped():
    fenced = '```json\n[{"field_code": "A1", "statement": "x"}]\n```'
    assert strip_json_markdown_fence(fenced) == '[{"field_code": "A1", "statement": "x"}]'


def test_plain_fenced_text_is_stripped():
    fenced = '```\n[{"field_code": "A1", "statement": "x"}]\n```'
    assert strip_json_markdown_fence(fenced) == '[{"field_code": "A1", "statement": "x"}]'


def test_prose_prefixed_fenced_text_is_stripped():
    # Reproduces the exact shape observed live in Packet #14's evidence-search
    # flag (e) verification: narrative prose, then a ```json fenced block --
    # the model's transition sentence before the "real" JSON answer.
    prose_then_fenced = (
        "Now I have comprehensive evidence. Let me compile the final JSON array.\n\n"
        '```json\n[{"field_code": "A1", "statement": "x"}]\n```'
    )
    assert strip_json_markdown_fence(prose_then_fenced) == '[{"field_code": "A1", "statement": "x"}]'


def test_integration_fenced_response_parses_correctly_through_apply_phrasing_guards():
    hyp = Hypothesis(
        dossier_id="DS-TEST", dossier_version=1, source_field="A1",
        source_section="opportunity", source_subfield="x",
        original_evidence_label="ESTIMATE", raw_dossier_text="raw",
        hypothesis_type="claim",
    )

    fenced_response = "```json\n" + json.dumps(
        [{"field_code": "A1", "statement": "A falsifiable statement."}]
    ) + "\n```"

    result = apply_phrasing_guards([hyp], fenced_response)
    assert result[0].phrasing_status == "PHRASED"
    assert result[0].statement == "A falsifiable statement."


def test_no_dollar_text_passes_through_unchanged():
    text = "A plain sentence with no currency figures."
    assert escape_markdown_dollar(text) == text


def test_single_dollar_figure_is_escaped():
    text = "Priced at $19/seat/month."
    assert escape_markdown_dollar(text) == "Priced at \\$19/seat/month."


def test_multiple_dollar_figures_are_all_escaped():
    # Reproduces the exact shape observed live in the P1.3 walkthrough's
    # D5 evidence proposal: two dollar figures in one string, which
    # Streamlit's default KaTeX rendering swallows between them.
    text = "Estimated at $0.01-0.03 originally, now under $0.001/message."
    assert escape_markdown_dollar(text) == "Estimated at \\$0.01-0.03 originally, now under \\$0.001/message."


def test_non_string_passes_through_unchanged():
    assert escape_markdown_dollar(None) is None
