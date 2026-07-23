"""
Tests for cross-project evaluation item a.3 (2026-07-23): Parameter
Extraction's number_input widget stayed stuck at its stale 0.0 baseline
value even after a genuine live extraction returned a real number for
that parameter -- the caption above it correctly flipped to EXTRACTED,
but the input box itself did not update.

Root cause: st.number_input's widget key only varied by
`flag_param_extraction` (a boolean that is True both immediately before
and immediately after clicking "Run live parameter extraction" -- only
the button click changes, not the flag). Streamlit only applies the
`value=` argument on a widget's FIRST render for a given key; once a
key has been rendered, later reruns with the same key reuse the
existing session-state value and ignore any new `value=` default. So a
widget first rendered pre-run with value=0.0 stayed at 0.0 forever,
even once `extracted[param]["value"]` held a real live number.

Fix: key on `param_extraction_live` (a.1's boolean, True only when a
genuine live result is actually being displayed) instead of the flag --
this genuinely changes between the pre-run and post-run renders, so
Streamlit correctly re-initializes the widget with the live value.

IMPORTANT CAVEAT (packet's own S0(c)): AppTest does not faithfully
reproduce Streamlit's stale-widget-key behavior across a rerun chained
through an explicit st.rerun() call (as opposed to a rerun triggered by
an ordinary widget interaction) -- confirmed via an isolated minimal
repro. This means these tests pass against BOTH the buggy key and the
fixed key, and must not be read as proof the bug is caught. They are
kept as basic characterization tests of the correct post-fix end state
only. The real proof is the packet's S4 manual acceptance test against
the live deployed app.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


def _fake_param_extraction(extractable):
    # Real, non-zero extracted value for CAC only -- the rest stay MISSING,
    # which is enough to prove the widget updates for the one that changed.
    return json.dumps([{"parameter_name": "CAC", "value": 42.0}])


@pytest.fixture
def patched_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    p = patch(
        "theoretical.simulation.parameter_extraction.call_anthropic_parameter_extraction",
        _fake_param_extraction,
    )
    p.start()
    yield
    p.stop()


def _click(at, label: str) -> bool:
    matches = [b for b in at.button if b.label == label]
    if not matches:
        return False
    matches[0].click().run()
    return True


def _cac_widget(at):
    matches = [ni for ni in at.number_input if ni.key.startswith("param_CAC_")]
    assert len(matches) == 1, f"expected exactly 1 CAC number_input, found {len(matches)}"
    return matches[0]


def test_widget_stays_zero_before_any_live_run(patched_call):
    """Before the live button is ever clicked, CAC's widget correctly
    shows the 0.0 baseline (nothing wrong here -- this is the honest
    pre-run state, not the bug)."""
    at = AppTest.from_file("app.py")
    at.run()
    at.sidebar.checkbox(key="flag_param_extraction").set_value(True)
    at.run()

    assert _cac_widget(at).value == 0.0


def test_widget_updates_to_real_value_after_genuine_live_run(patched_call):
    """Post-fix end state: after clicking 'Run live parameter
    extraction' and getting a real CAC=42.0 back, the number_input shows
    42.0 and the caption says EXTRACTED. See module docstring's caveat --
    this does not by itself prove the bug would have been caught."""
    at = AppTest.from_file("app.py")
    at.run()
    at.sidebar.checkbox(key="flag_param_extraction").set_value(True)
    at.run()

    assert _click(at, "Run live parameter extraction")
    assert at.exception == [], at.exception

    cac_widget = _cac_widget(at)
    assert cac_widget.value == 42.0, (
        f"CAC widget still shows {cac_widget.value} after a genuine live "
        "extraction returned 42.0."
    )

    captions = [c.value for c in at.caption]
    assert any("EXTRACTED" in c for c in captions), captions
