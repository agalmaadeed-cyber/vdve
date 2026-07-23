"""
Tests for cross-project evaluation item a.2 (2026-07-23): separate Mock
Evidence from Live Evidence clearly -- default OFF for the "Load mock
evidence proposals" checkbox (previously defaulted ON whenever Live
Evidence Search was off), plus a persistent MOCK badge on the Dossier
field itself (is_mock_evidence), surfaced in the Ranking table -- not
just a session-only caption that vanishes the moment a proposal is
approved.

Uses AppTest for the same reason as test_app_status_labels.py: this is
a UI-rendering + session-state class of bug, invisible to plain unit
tests on the underlying theoretical/ modules alone (those are covered
separately in tests/theoretical/evidence_gathering/test_review.py).
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_mock_checkbox_defaults_unchecked():
    """Core a.2 fix: previously defaulted to checked whenever Live Evidence
    Search was off (value=not flag_evidence). Now always defaults False,
    regardless of flag_evidence -- loading mock data is always an active,
    explicit choice."""
    at = AppTest.from_file("app.py")
    at.run()
    mock_cbs = [c for c in at.checkbox if c.label.startswith("Load mock evidence")]
    assert len(mock_cbs) == 1, f"expected exactly 1 mock-evidence checkbox, found {len(mock_cbs)}"
    assert mock_cbs[0].value is False


def _claims_and_unknowns_dataframes(at):
    dfs = [d for d in at.dataframe if "adjustment_status" in d.value.columns and len(d.value) > 0]
    assert len(dfs) >= 1, f"expected at least 1 non-empty ranking dataframe, found {len(dfs)}"
    return dfs


def test_approved_mock_proposal_gets_a_persistent_badge_in_ranking_table():
    """The actual founder-facing behavior: approve one mock proposal (F4,
    which stays a hypothesis post-approval since its label is ASSUMPTION,
    not upgraded to CONFIRMED), then confirm the Ranking table shows
    exactly one 'evidence' == '🧪 MOCK' row and every other row blank."""
    at = AppTest.from_file("app.py")
    at.run()

    mock_cbs = [c for c in at.checkbox if c.label.startswith("Load mock evidence")]
    assert len(mock_cbs) == 1
    mock_cbs[0].set_value(True)
    at.run()

    approve_cbs = [c for c in at.checkbox if c.key and c.key.startswith("approve_F4_")]
    assert len(approve_cbs) == 1, "expected exactly one approval checkbox for F4's mock proposal"
    approve_cbs[0].set_value(True)
    at.run()

    apply_buttons = [b for b in at.button if b.label == "Apply Approved Evidence"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()
    assert at.exception == [], f"exception after applying approved evidence: {at.exception}"

    dfs = _claims_and_unknowns_dataframes(at)
    assert any("evidence" in df.value.columns for df in dfs), "Ranking table must carry the new 'evidence' badge column"

    mock_rows = []
    other_rows = []
    for df in dfs:
        if "evidence" not in df.value.columns:
            continue
        for _, row in df.value.iterrows():
            (mock_rows if row["field"] == "F4" else other_rows).append(row)

    assert len(mock_rows) == 1, f"expected exactly one F4 row across both tables, found {len(mock_rows)}"
    assert mock_rows[0]["evidence"] == "🧪 MOCK"
    assert all(r["evidence"] == "" for r in other_rows), [r["evidence"] for r in other_rows if r["evidence"] != ""]
