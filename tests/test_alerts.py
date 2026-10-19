"""Alert policies and NRQL conditions: the models, and their reconcile."""

import pytest
from pydantic import ValidationError

from newrelic_as_code import (
    AlertPolicy,
    BaselineTerm,
    ConditionNrql,
    Expiration,
    NrqlBaselineCondition,
    NrqlStaticCondition,
    Signal,
    StaticTerm,
)


def _policy(name="P"):
    return AlertPolicy(name=name, incident_preference="PER_CONDITION")


def _static_term(threshold=1.0, **kwargs):
    return StaticTerm(
        operator="ABOVE",
        priority="CRITICAL",
        threshold=threshold,
        threshold_duration=300,
        threshold_occurrences="ALL",
        **kwargs,
    )


def _static(name, policy, threshold=1.0):
    return NrqlStaticCondition(
        policy=policy,
        name=name,
        enabled=True,
        nrql=ConditionNrql(query="SELECT count(*) FROM TransactionError"),
        terms=[_static_term(threshold)],
    )


def _baseline(name, policy):
    return NrqlBaselineCondition(
        policy=policy,
        name=name,
        enabled=True,
        nrql=ConditionNrql(query="SELECT average(duration) FROM Transaction"),
        baseline_direction="UPPER_ONLY",
        terms=[
            BaselineTerm(
                operator="ABOVE",
                priority="CRITICAL",
                threshold=3,
                threshold_duration=300,
                threshold_occurrences="ALL",
            )
        ],
    )


# -- models ---------------------------------------------------------------------


def test_policy_input():
    assert _policy().as_nr_dict() == {"name": "P", "incidentPreference": "PER_CONDITION"}


def test_static_condition_input():
    condition = NrqlStaticCondition(
        policy=_policy(),
        name="Errors",
        enabled=True,
        nrql=ConditionNrql(query="SELECT count(*) FROM TransactionError", data_account_id=9),
        runbook_url="https://runbook",
        signal=Signal(aggregation_window=60, fill_option="STATIC", fill_value=0),
        expiration=Expiration(expiration_duration=600, open_violation_on_expiration=True),
        terms=[
            _static_term(10),
            StaticTerm(
                operator="ABOVE_OR_EQUALS",
                priority="WARNING",
                threshold=5,
                threshold_duration=600,
                threshold_occurrences="AT_LEAST_ONCE",
            ),
        ],
    )
    # The policy is the create mutation's policyId argument, not part of the
    # input, and the type picks the mutation.
    assert condition.as_nr_dict() == {
        "name": "Errors",
        "enabled": True,
        "nrql": {"query": "SELECT count(*) FROM TransactionError", "dataAccountId": 9},
        "runbookUrl": "https://runbook",
        "signal": {"aggregationWindow": 60, "fillOption": "STATIC", "fillValue": 0},
        "expiration": {"expirationDuration": 600, "openViolationOnExpiration": True},
        "terms": [
            {
                "operator": "ABOVE",
                "priority": "CRITICAL",
                "threshold": 10,
                "thresholdDuration": 300,
                "thresholdOccurrences": "ALL",
            },
            {
                "operator": "ABOVE_OR_EQUALS",
                "priority": "WARNING",
                "threshold": 5,
                "thresholdDuration": 600,
                "thresholdOccurrences": "AT_LEAST_ONCE",
            },
        ],
    }


def test_baseline_condition_input():
    d = _baseline("Latency", _policy()).as_nr_dict()
    assert d["baselineDirection"] == "UPPER_ONLY"
    assert d["terms"][0]["operator"] == "ABOVE"
    assert "policy" not in d


def test_condition_keeps_the_policy_object():
    # References are followed by object identity, so validation must not copy.
    policy = _policy()
    assert _static("c", policy).policy is policy


def test_fields_new_relic_requires_have_no_defaults():
    with pytest.raises(ValidationError, match="incident_preference"):
        AlertPolicy(name="P")
    with pytest.raises(ValidationError, match="enabled"):
        NrqlStaticCondition(policy=_policy(), name="c", nrql=ConditionNrql(query="SELECT 1"))
    with pytest.raises(ValidationError, match="threshold_occurrences"):
        StaticTerm(operator="ABOVE", priority="CRITICAL", threshold=1, threshold_duration=60)
