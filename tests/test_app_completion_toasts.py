"""
Tests for cross-project evaluation item a.10 (2026-07-24): active
completion notifications instead of passive indicator updates.

Before this fix, every genuine step completion in this app (a live LLM
call finishing, evidence being applied, a cycle record being finalized,
Gate 4 sign-off being confirmed) ended in a silent st.rerun() with no
signal at all beyond the page re-rendering -- the founder had to notice
the page changed on its own. The fix adds st.toast() (an ephemeral,
auto-dismissing notification) immediately before each of these 9
completion-triggering st.rerun() calls, verified empirically (outside
this test suite, via a minimal AppTest probe) to survive the immediate
following rerun.

Scope of this file: representative AppTest coverage for 3 of the 9 sites
(hypothesis phrasing, risk adjustment, parameter extraction) using the
same _enable_all_flags_and_approve()-style setup already established in
test_app_status_labels.py. The remaining 6 sites (evidence search,
evidence review applied, qualitative probes, recommendation, cycle
record finalized, Gate 4 sign-off) follow the mechanically identical
"st.toast(...) immediately before st.rerun()" pattern -- confirmed by
direct diff inspection, not independently re-driven through AppTest here,
since Gate 4 sign-off in particular requires walking the full live cycle
through to a finalized cycle record, a disproportionate setup cost for a
one-line mechanically-uniform addition already visible in the diff.

Uses AppTest for the same reason as test_app_status_labels.py and
test_app_mock_evidence_badge.py: st.toast() is a UI-rendering call,
invisible to plain unit tests on the underlying theoretical/ modules.
"""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest


def _fake_phrasing(hypotheses):
    return json.dumps(
        [{"hypothesis_id": h["hypothesis_id"], "phrased_text": h["raw_dossier_text"]} for h in hypotheses]
    )


def _fake_risk_adjustment(hypotheses):
    return "[]"


def _fake_param_extraction(extractable):
    return "[]"


@pytest.fixture
def patched_llm_calls(monkeypatch):
    """Same monkeypatch.setenv discipline as test_app_status_labels.py's
    fixture -- never a module-level os.environ.setdefault (would leak
    into the whole pytest session and un-skip the two dedicated
    live-API-cost tests)."""
    from unittest.mock import patch

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    patches = [
        patch("theoretical.hypothesis_extraction.phrasing.call_anthropic_phrasing", _fake_phrasing),
        patch("theoretical.hypothesis_extraction.ranking.call_anthropic_risk_adjustment", _fake_risk_adjustment),
        patch(
            "theoretical.simulation.parameter_extraction.call_anthropic_parameter_extraction",
            _fake_param_extraction,
        ),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def _click(at, label: str) -> bool:
    matches = [b for b in at.button if b.label == label]
    if not matches:
        return False
    matches[0].click().run()
    return True


def _toast_messages(at):
    return [t.value for t in at.toast]


def test_hypothesis_phrasing_completion_fires_a_toast(patched_llm_calls):
    at = AppTest.from_file("app.py")
    at.run()
    at.sidebar.checkbox(key="flag_phrasing").set_value(True)
    at.run()

    assert _click(at, "Run live phrasing"), "'Run live phrasing' button not found"
    assert at.exception == [], f"exception after clicking 'Run live phrasing': {at.exception}"
    assert "Hypothesis phrasing complete." in _toast_messages(at), _toast_messages(at)


def test_risk_adjustment_completion_fires_a_toast(patched_llm_calls):
    at = AppTest.from_file("app.py")
    at.run()
    at.sidebar.checkbox(key="flag_risk_adj").set_value(True)
    at.run()

    assert _click(at, "Run live risk adjustment"), "'Run live risk adjustment' button not found"
    assert at.exception == [], f"exception after clicking 'Run live risk adjustment': {at.exception}"
    assert "Risk adjustment (ranking) complete." in _toast_messages(at), _toast_messages(at)


def test_parameter_extraction_completion_fires_a_toast(patched_llm_calls):
    at = AppTest.from_file("app.py")
    at.run()
    at.sidebar.checkbox(key="flag_param_extraction").set_value(True)
    at.run()
    _click(at, "Approve Parameters")

    assert _click(at, "Run live parameter extraction"), "'Run live parameter extraction' button not found"
    assert at.exception == [], f"exception after clicking 'Run live parameter extraction': {at.exception}"
    assert "Parameter extraction complete." in _toast_messages(at), _toast_messages(at)


def test_no_toast_fires_before_any_button_is_clicked():
    """Baseline sanity check: loading the app fresh (no button clicks at
    all) must not fire any toast -- these are completion notifications,
    not load-time noise."""
    at = AppTest.from_file("app.py")
    at.run()
    assert _toast_messages(at) == []
