"""
Tests for cross-project evaluation item b.4 (2026-07-24): VDVE's
app-facing display name changed to "The Crucible", per the founder's
own decision (candidates offered: The Crucible, Stress Lab, Proof
Engine, Reality Check, The Verdict Room -- founder chose The Crucible).

Explicitly scoped as a display-name-only change: no repo rename, no
package rename, no internal module/function/variable renamed. The
module docstring and README.md's opening line still say "VDVE" on
purpose -- that's internal engineering documentation, not "the
interface" the founder's decision refers to.

Uses AppTest for the same reason as test_app_status_labels.py,
test_app_mock_evidence_badge.py, and test_app_completion_toasts.py:
the rendered title is a UI-rendering fact, invisible to a plain source
grep. Note: st.set_page_config()'s page_title (the browser tab text)
is not exposed through AppTest's public API -- that half of this fix
is verified by a direct source-string assertion instead, disclosed
here rather than silently skipped.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PY = Path(__file__).resolve().parents[1] / "app.py"


def test_page_title_shows_the_crucible_not_vdve():
    at = AppTest.from_file("app.py")
    at.run()
    assert len(at.title) == 1
    rendered_title = at.title[0].value
    assert rendered_title == "The Crucible - Theoretical Validation Cycle (P1.1/P1.2)"
    assert "VDVE" not in rendered_title


def test_browser_tab_title_source_string_updated():
    source = APP_PY.read_text(encoding="utf-8")
    assert 'page_title="The Crucible - Theoretical Validation Cycle"' in source
    assert 'page_title="VDVE - Theoretical Validation Cycle"' not in source
