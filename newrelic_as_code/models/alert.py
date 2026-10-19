"""
Alert policies and NRQL alert conditions.

Each model mirrors its NerdGraph input type field for field, including which
fields are required: a field NerdGraph requires has no default here, and an
optional one defaults to None, which leaves it to New Relic's own default.

- ``AlertPolicy`` — ``AlertsPolicyInput``.
- ``NrqlStaticCondition`` — ``AlertsNrqlConditionStaticInput``.
- ``NrqlBaselineCondition`` — ``AlertsNrqlConditionBaselineInput``.

As in New Relic, a condition points at the policy it belongs to (``policy``,
NerdGraph's ``policyId``); a policy doesn't list its conditions.

Not modeled: fields NerdGraph marks deprecated (``violationTimeLimit``,
``valueFunction``, ``nrql.evaluationOffset``), outlier conditions (removed by
New Relic in 2022), and the ``CUSTOM`` incident preference (its grouping
settings aren't part of ``AlertsPolicyInput``).
"""

from typing import Any, ClassVar, Literal

from .base import NrModel, NrResource


IncidentPreference = Literal["PER_POLICY", "PER_CONDITION", "PER_CONDITION_AND_TARGET"]
Priority = Literal["CRITICAL", "WARNING"]
ThresholdOccurrences = Literal["ALL", "AT_LEAST_ONCE"]
StaticOperator = Literal[
    "ABOVE", "ABOVE_OR_EQUALS", "BELOW", "BELOW_OR_EQUALS", "EQUALS", "NOT_EQUALS"
]
BaselineDirection = Literal["LOWER_ONLY", "UPPER_AND_LOWER", "UPPER_ONLY"]
SignalSeasonality = Literal["NEW_RELIC_CALCULATION", "HOURLY", "DAILY", "WEEKLY", "NONE"]
AggregationMethod = Literal["CADENCE", "EVENT_FLOW", "EVENT_TIMER"]
FillOption = Literal["NONE", "LAST_VALUE", "STATIC"]


class AlertPolicy(NrResource):
    """``AlertsPolicyInput``: a container for conditions that decides how their
    violations are grouped into issues."""

    name: str
    incident_preference: IncidentPreference


class ConditionNrql(NrModel):
    """``AlertsNrqlConditionQueryInput``: the query a condition evaluates."""

    query: str
    data_account_id: int | None = None


class Signal(NrModel):
    """``AlertsNrqlConditionSignalInput``: how query results become a signal."""

    aggregation_window: int | None = None
    aggregation_method: AggregationMethod | None = None
    aggregation_delay: int | None = None
    aggregation_timer: int | None = None
    evaluation_delay: int | None = None
    fill_option: FillOption | None = None
    fill_value: float | None = None
    slide_by: int | None = None
    polling_frequency: int | None = None


class Expiration(NrModel):
    """``AlertsNrqlConditionExpirationInput``: loss-of-signal settings."""

    expiration_duration: int | None = None
    open_violation_on_expiration: bool | None = None
    close_violations_on_expiration: bool | None = None
    ignore_on_expected_termination: bool | None = None


class Prediction(NrModel):
    """``AlertsNrqlConditionPredictionInput``: predictive alerting for a static term."""

    predict_by: int | None = None
    prefer_prediction_violation: bool | None = None


class StaticTerm(NrModel):
    """``AlertsNrqlConditionTermsInput``: one threshold of a static condition."""

    operator: StaticOperator
    priority: Priority
    threshold: float
    threshold_duration: int
    threshold_occurrences: ThresholdOccurrences
    prediction: Prediction | None = None
    disable_health_status_reporting: bool | None = None
    disable_event_creation: bool | None = None


class BaselineTerm(NrModel):
    """``AlertsNrqlDynamicConditionTermsInput``: one threshold of a baseline condition.

    ``threshold`` is in standard deviations from the baseline. New Relic only
    accepts ``ABOVE`` as the operator; the direction is the condition's
    ``baseline_direction``.
    """

    operator: Literal["ABOVE"]
    priority: Priority
    threshold: float
    threshold_duration: int
    threshold_occurrences: ThresholdOccurrences
    disable_health_status_reporting: bool | None = None
    disable_event_creation: bool | None = None


class _NrqlCondition(NrResource):
    """Fields every NRQL condition input shares.

    ``condition_type`` is the condition's ``AlertsNrqlConditionType``, which
    picks the create/update mutation. ``policy`` is the ``policyId`` argument
    of the create mutation. Neither is part of the input itself.
    """

    condition_type: ClassVar[str]

    policy: AlertPolicy
    name: str
    enabled: bool
    nrql: ConditionNrql
    description: str | None = None
    runbook_url: str | None = None
    title_template: str | None = None
    signal: Signal | None = None
    expiration: Expiration | None = None
    violation_time_limit_seconds: int | None = None
    target_entity: str | None = None

    def as_nr_dict(self) -> dict[str, Any]:
        result = super().as_nr_dict()
        del result["policy"]
        return result


class NrqlStaticCondition(_NrqlCondition):
    """``AlertsNrqlConditionStaticInput``: alert when the signal crosses a fixed threshold."""

    condition_type: ClassVar[str] = "STATIC"

    terms: list[StaticTerm] | None = None


class NrqlBaselineCondition(_NrqlCondition):
    """``AlertsNrqlConditionBaselineInput``: alert when the signal deviates from its baseline."""

    condition_type: ClassVar[str] = "BASELINE"

    baseline_direction: BaselineDirection
    terms: list[BaselineTerm] | None = None
    signal_seasonality: SignalSeasonality | None = None


AnyNrqlCondition = NrqlStaticCondition | NrqlBaselineCondition
