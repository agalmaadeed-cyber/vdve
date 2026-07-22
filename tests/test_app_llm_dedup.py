"""
Tests for Packet B (P1.4 Packet #2): eliminating redundant live-LLM
calls caused by Streamlit's full-script-rerun-on-any-interaction
model. Uses Streamlit's AppTest harness (streamlit.testing.v1) since
this is exactly the class of bug this project's own history has
repeatedly found invisible to plain unit tests (session-state /
rerun-timing bugs) -- see phase1_decisions_log.md and
vdve_project_reference.md Section 6's "Key lesson".

IMPORTANT test-authoring note, discovered while building this suite:
AppTest re-execs app.py fresh on every .run() call rather than
reusing a cached module object, so `unittest.mock.patch("app.call_
anthropic_X", ...)` does NOT intercept calls made during an AppTest
run (app.py's own `from theoretical... import call_anthropic_X`
statement re-resolves from the ORIGIN module on every rerun). Patch
the origin module instead (e.g.
"theoretical.hypothesis_extraction.phrasing.call_anthropic_phrasing").
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


def _fake_phrasing(hypotheses):
    return json.dumps([{"field_code": h.source_field, "statement": "x"} for h in hypotheses])


def _fake_risk_adjustment(hypotheses):
    return "[]"


def _fake_evidence(hypotheses):
    return "[]"


def _fake_param_extraction(extractable):
    return "[]"


def _fake_probe(spec):
    return json.dumps({"hypothesis_id": spec["target_hypothesis_id"], "severity": "LOW", "rationale": "test"})


def _fake_recommendation(payload):
    return json.dumps({"outcome": "Reject", "narrative": "test", "decisive_evidence": ["A1"]})


@pytest.fixture
def patched_llm_calls(monkeypatch):
    """
    Patches all six origin call_anthropic_* functions with counting
    fakes. ANTHROPIC_API_KEY is set via monkeypatch (auto-reverted
    after this test only) so app.py's sidebar flags render -- NEVER
    via a module-level os.environ.setdefault(), which would leak into
    the whole pytest session and silently un-skip the two dedicated
    live-API tests (test_phrasing_live.py, test_agent_live.py), which
    are deliberately skip-gated because each costs one real API call.
    An earlier draft of this file made exactly that mistake -- caught
    by re-running the FULL suite (not just this file) before finalizing,
    which showed 181 passed / 0 skipped instead of the expected
    ~179 passed / 2 skipped. Fixed here; see this packet's S0.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    counts = {"phrasing": 0, "risk_adj": 0, "evidence": 0, "param_extraction": 0, "probe": 0, "recommendation": 0}

    def counting(name, fn):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            return fn(*args, **kwargs)
        return wrapper

    patches = [
        patch("theoretical.hypothesis_extraction.phrasing.call_anthropic_phrasing", counting("phrasing", _fake_phrasing)),
        patch("theoretical.hypothesis_extraction.ranking.call_anthropic_risk_adjustment", counting("risk_adj", _fake_risk_adjustment)),
        patch("theoretical.evidence_gathering.agent.call_anthropic_evidence_search", counting("evidence", _fake_evidence)),
        patch("theoretical.simulation.parameter_extraction.call_anthropic_parameter_extraction", counting("param_extraction", _fake_param_extraction)),
        patch("theoretical.stress_tests.engine.call_anthropic_probe", counting("probe", _fake_probe)),
        patch("theoretical.decision.outcome.call_anthropic_recommendation", counting("recommendation", _fake_recommendation)),
    ]
    for p in patches:
        p.start()
    yield counts
    for p in patches:
        p.stop()


def _click(at, label: str) -> bool:
    matches = [b for b in at.button if b.label == label]
    if not matches:
        return False
    matches[0].click().run()
    return True


def _enable_all_flags_and_approve(at):
    at.run()
    for key in ["flag_phrasing", "flag_risk_adj", "flag_param_extraction", "flag_probes", "flag_evidence", "flag_recommendation"]:
        at.sidebar.checkbox(key=key).set_value(True)
    at.run()
    mock_cbs = [c for c in at.checkbox if c.label.startswith("Load mock evidence")]
    if mock_cbs:
        mock_cbs[0].set_value(False)
    at.run()
    _click(at, "Approve Parameters")


def test_one_click_per_step_makes_exactly_one_real_call_each(patched_llm_calls):
    """
    Core acceptance property (Decision, this packet's S0): clicking
    each step's "Run live ..." button exactly once must produce
    exactly one real call for every step except qualitative probes,
    which legitimately fans out to one call per generated spec
    (top-3 ranked claims -- 3 calls is correct here, not a bug).
    """
    at = AppTest.from_file("app.py")
    _enable_all_flags_and_approve(at)

    for label in [
        "Run live phrasing", "Run live risk adjustment", "Run live parameter extraction",
        "Run live evidence search", "Run live qualitative probes", "Run live recommendation",
    ]:
        assert _click(at, label), f"button '{label}' not found"
        assert at.exception == [], f"exception after clicking '{label}': {at.exception}"

    assert patched_llm_calls == {
        "phrasing": 1, "risk_adj": 1, "evidence": 1,
        "param_extraction": 1, "probe": 3, "recommendation": 1,
    }
    # Session counter must reflect the TRUE call count (1+1+1+1+3+1=8), not
    # "one increment per pipeline step" (which would silently undercount probes).
    assert at.session_state["api_call_count"] == 8


def test_unrelated_reruns_never_repeat_a_call(patched_llm_calls):
    """
    The actual bug this packet fixes: a rerun triggered by an
    unrelated interaction must never repeat a call whose inputs
    haven't changed. Reproduces the founder's real 2026-07-18
    scenario (toggling several flags back and forth) as a regression
    test.
    """
    at = AppTest.from_file("app.py")
    _enable_all_flags_and_approve(at)
    for label in [
        "Run live phrasing", "Run live risk adjustment", "Run live parameter extraction",
        "Run live evidence search", "Run live qualitative probes", "Run live recommendation",
    ]:
        _click(at, label)

    baseline = dict(patched_llm_calls)

    # Five plain reruns, no input changes.
    for _ in range(5):
        at.run()
    assert patched_llm_calls == baseline

    # Toggle an unrelated flag off and back on -- exactly the pattern
    # that caused the real cost spike -- must still make zero new calls.
    at.sidebar.checkbox(key="flag_probes").set_value(False)
    at.run()
    at.sidebar.checkbox(key="flag_probes").set_value(True)
    at.run()
    assert patched_llm_calls == baseline

    # No "Run live ..." buttons should be showing -- every cache is still valid.
    assert [b.label for b in at.button if b.label.startswith("Run live")] == []


def test_no_button_click_means_zero_calls(patched_llm_calls):
    """Enabling every flag alone, with no button ever clicked, must make zero API calls."""
    at = AppTest.from_file("app.py")
    _enable_all_flags_and_approve(at)
    assert patched_llm_calls == {
        "phrasing": 0, "risk_adj": 0, "evidence": 0,
        "param_extraction": 0, "probe": 0, "recommendation": 0,
    }
