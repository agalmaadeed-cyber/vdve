"""
Orchestration only (Decision P1.0.10 point 7). Ties the deterministic
content assembly (markdown_builder) to the one controlled format
conversion (docx_renderer) into a single call the UI layer can use
directly in a Streamlit download_button, same one-step pattern this
app already uses for its JSON export (app.py Step 10).
"""

from __future__ import annotations

from venture_story.docx_renderer import render_markdown_to_docx
from venture_story.markdown_builder import generate_intermediate_markdown


def generate_venture_story(
    dossier: dict,
    cycle_record: dict,
    gate4_verdict: dict,
    signed_off_at: str,
    scenarios: dict,
) -> bytes:
    """Returns .docx bytes, ready for st.download_button."""
    markdown_text = generate_intermediate_markdown(
        dossier, cycle_record, gate4_verdict, signed_off_at, scenarios
    )
    return render_markdown_to_docx(markdown_text)
