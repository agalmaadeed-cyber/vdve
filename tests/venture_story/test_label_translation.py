import pytest

from venture_story.label_translation import (
    EVIDENCE_LABEL_TRANSLATION,
    FIELD_PROMPTS,
    KILL_STATUS_TRANSLATION,
    METRIC_LABELS,
    METRIC_ORDER,
    SEVERITY_TRANSLATION,
    STRESS_OUTCOME_TRANSLATION,
)

ALL_TRANSLATION_DICTS = {
    "EVIDENCE_LABEL_TRANSLATION": EVIDENCE_LABEL_TRANSLATION,
    "STRESS_OUTCOME_TRANSLATION": STRESS_OUTCOME_TRANSLATION,
    "SEVERITY_TRANSLATION": SEVERITY_TRANSLATION,
    "KILL_STATUS_TRANSLATION": KILL_STATUS_TRANSLATION,
    "FIELD_PROMPTS": FIELD_PROMPTS,
    "METRIC_LABELS": METRIC_LABELS,
}


@pytest.mark.parametrize("dict_name", ALL_TRANSLATION_DICTS.keys())
def test_dictionary_is_non_empty(dict_name):
    assert len(ALL_TRANSLATION_DICTS[dict_name]) > 0


@pytest.mark.parametrize("dict_name", ALL_TRANSLATION_DICTS.keys())
def test_every_value_is_a_non_empty_string(dict_name):
    for key, value in ALL_TRANSLATION_DICTS[dict_name].items():
        assert isinstance(value, str) and value.strip(), f"{dict_name}[{key!r}] is not a non-empty string"


@pytest.mark.parametrize("dict_name", ALL_TRANSLATION_DICTS.keys())
def test_every_value_is_distinct_from_its_key(dict_name):
    # Catches an accidental identity mapping / copy-paste no-op.
    for key, value in ALL_TRANSLATION_DICTS[dict_name].items():
        assert value != key, f"{dict_name}[{key!r}] == {key!r} -- looks like a copy-paste no-op"


def test_metric_order_is_non_empty_and_matches_metric_labels_keys():
    assert len(METRIC_ORDER) > 0
    assert set(METRIC_ORDER) == set(METRIC_LABELS.keys())
