import json

from theoretical.llm_utils import strip_json_markdown_fence
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
