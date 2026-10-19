"""Alert policies and NRQL conditions: the models, and their reconcile.

As in ``test_reconcile``, only ``NerdGraphClient.call`` is stubbed, so the real
reconcile code decides which mutations to make.
"""

import base64

import pytest
from pydantic import ValidationError

from newrelic_as_code import (
    AlertPolicy,
    BaselineTerm,
    ConditionNrql,
    Expiration,
    NewRelicUpdater,
    NewRelicUpdaterError,
    NrqlBaselineCondition,
    NrqlStaticCondition,
    Signal,
    StaticTerm,
)
from newrelic_as_code.updater import _guid_domain_id


TAG_KEY = "managed-by"
TAG_VALUE = "test-deploy"


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


def test_update_renders_unset_fields_as_nulls():
    d = _static("c", _policy()).as_nr_dict(nulls=True)
    assert d["description"] is None
    assert d["signal"] is None
    assert d["nrql"] == {"query": "SELECT count(*) FROM TransactionError", "dataAccountId": None}
    assert d["terms"][0]["prediction"] is None
    assert "policy" not in d


def test_guid_domain_id():
    assert _guid_domain_id(_policy_guid(4242)) == "4242"


# -- reconcile ------------------------------------------------------------------


def _policy_guid(policy_id):
    raw = f"1|AIOPS|POLICY|{policy_id}".encode()
    return base64.b64encode(raw).decode().rstrip("=")


class FakeAlertsUpdater(NewRelicUpdater):
    """Updater over a scripted account of alert policies and their conditions.

    ``policies`` maps policy name -> (policy id, managed?); ``conditions`` maps
    policy id -> {condition name: (condition id, type)}. Every mutation is
    recorded in ``self.calls``; condition updates also keep their payload in
    ``self.payloads``.
    """

    def __init__(self, policies=None, conditions=None, **kwargs):
        super().__init__(
            account_id=1,
            api_key="k",
            managed_tag_key=TAG_KEY,
            managed_tag_value=TAG_VALUE,
            **kwargs,
        )
        self._policies = policies or {}
        self._conditions = conditions or {}
        self.calls = []
        self.payloads = {}
        self.client.call = self._fake_call

    def _entity(self, name):
        policy_id, managed = self._policies[name]
        tags = [{"key": TAG_KEY, "values": [TAG_VALUE]}] if managed else []
        return {"guid": _policy_guid(policy_id), "name": name, "tags": tags}

    def _fake_call(self, query, variables):
        if "entitySearch" in query:
            nrql = variables["query"]
            if "type = 'POLICY'" not in nrql:
                names = []  # no dashboards in this account
            elif f"tags.`{TAG_KEY}`" in nrql:
                names = [n for n, (_, managed) in self._policies.items() if managed]
            else:
                wanted = nrql.split("name = '", 1)[1].split("'", 1)[0]
                names = [n for n in self._policies if wanted in n]
            entities = [self._entity(n) for n in names]
            return {"actor": {"entitySearch": {"results": {"entities": entities}}}}
        if "nrqlConditionsSearch" in query:
            live = self._conditions.get(int(variables["policyId"]), {})
            page = {
                "nextCursor": None,
                "nrqlConditions": [
                    {"id": cid, "name": name, "type": ctype} for name, (cid, ctype) in live.items()
                ],
            }
            return {"actor": {"account": {"alerts": {"nrqlConditionsSearch": page}}}}
        if "taggingAddTagsToEntity" in query:
            return {"taggingAddTagsToEntity": {"errors": None}}
        if "alertsPolicyCreate" in query:
            self.calls.append(("create policy", variables["policy"]["name"]))
            return {"alertsPolicyCreate": {"id": "77", "entityGuid": _policy_guid(77)}}
        if "alertsPolicyUpdate" in query:
            self.calls.append(("update policy", variables["id"]))
            return {"alertsPolicyUpdate": {"id": variables["id"]}}
        if "alertsPolicyDelete" in query:
            self.calls.append(("delete policy", variables["id"]))
            return {"alertsPolicyDelete": {"id": variables["id"]}}
        for kind in ("Static", "Baseline"):
            if f"alertsNrqlCondition{kind}Create" in query:
                name = variables["condition"]["name"]
                self.calls.append((f"create {kind.lower()}", variables["policyId"], name))
                return {f"alertsNrqlCondition{kind}Create": {"id": f"new-{name}"}}
            if f"alertsNrqlCondition{kind}Update" in query:
                self.calls.append((f"update {kind.lower()}", variables["id"]))
                self.payloads[variables["id"]] = variables["condition"]
                return {f"alertsNrqlCondition{kind}Update": {"id": variables["id"]}}
        if "alertsConditionDelete" in query:
            self.calls.append(("delete condition", variables["id"]))
            return {"alertsConditionDelete": {"id": variables["id"]}}
        raise AssertionError(f"unexpected query: {query}")


def test_creates_policy_then_its_conditions():
    # Only the conditions are passed; their policy is reached by reference.
    policy = _policy()
    updater = FakeAlertsUpdater()
    updater.sync([_static("a", policy), _baseline("b", policy)])
    assert updater.calls == [
        ("create policy", "P"),
        ("create static", "77", "a"),
        ("create baseline", "77", "b"),
    ]


def test_updates_managed_policy_and_reconciles_its_conditions():
    policy = _policy()
    updater = FakeAlertsUpdater(
        policies={"P": (5, True)},
        conditions={5: {"keep": ("c1", "STATIC"), "stale": ("c2", "STATIC")}},
    )
    updater.sync([_static("keep", policy), _static("new", policy)])
    assert updater.calls == [
        ("update policy", "5"),
        ("update static", "c1"),
        ("create static", "5", "new"),
        ("delete condition", "c2"),
    ]
    # Unset fields go out as nulls, so New Relic resets them to its defaults.
    assert updater.payloads["c1"]["runbookUrl"] is None


def test_policy_without_conditions_loses_its_conditions():
    updater = FakeAlertsUpdater(policies={"P": (5, True)}, conditions={5: {"c": ("c1", "STATIC")}})
    updater.sync([_policy()])
    assert updater.calls == [("update policy", "5"), ("delete condition", "c1")]


def test_condition_type_change_recreates():
    updater = FakeAlertsUpdater(policies={"P": (5, True)}, conditions={5: {"c": ("c1", "STATIC")}})
    updater.sync([_baseline("c", _policy())])
    assert updater.calls == [
        ("update policy", "5"),
        ("delete condition", "c1"),
        ("create baseline", "5", "c"),
    ]


def test_same_condition_name_in_two_policies():
    first, second = _policy("A"), _policy("B")
    updater = FakeAlertsUpdater()
    updater.sync([_static("c", first), _static("c", second)])
    assert [call[0] for call in updater.calls] == [
        "create policy",
        "create policy",
        "create static",
        "create static",
    ]


def test_deletes_orphaned_managed_policy_only():
    updater = FakeAlertsUpdater(policies={"Old": (5, True), "Hand-built": (6, False)})
    updater.sync([])
    assert updater.calls == [("delete policy", "5")]


def test_refuses_to_clobber_unmanaged_policy():
    updater = FakeAlertsUpdater(policies={"Hand-built": (6, False)})
    with pytest.raises(NewRelicUpdaterError, match="not managed by this tool"):
        updater.sync([_policy("Hand-built")])
    assert updater.calls == []


def test_refuses_duplicate_condition_names_in_a_policy():
    policy = _policy()
    updater = FakeAlertsUpdater()
    with pytest.raises(NewRelicUpdaterError, match="Duplicate condition name 'c' in policy"):
        updater.sync([_static("c", policy), _baseline("c", policy)])


def test_refuses_duplicate_live_condition_names():
    updater = FakeAlertsUpdater(policies={"P": (5, True)})
    original = updater._fake_call

    def duplicate_conditions(query, variables):
        # Two live conditions sharing a name can't be expressed in the
        # name-keyed fake, so answer the search directly.
        if "nrqlConditionsSearch" in query:
            dup = [{"id": i, "name": "c", "type": "STATIC"} for i in ("c1", "c2")]
            page = {"nextCursor": None, "nrqlConditions": dup}
            return {"actor": {"account": {"alerts": {"nrqlConditionsSearch": page}}}}
        return original(query, variables)

    updater.client.call = duplicate_conditions
    with pytest.raises(NewRelicUpdaterError, match="refusing to guess"):
        updater.sync([_static("c", _policy())])


def test_dry_run_makes_no_mutations():
    existing, new = _policy("P"), _policy("Q")
    updater = FakeAlertsUpdater(
        policies={"P": (5, True), "Old": (6, True)},
        conditions={5: {"stale": ("c2", "STATIC")}},
        dry_run=True,
    )
    updater.sync([_static("a", existing), _static("b", new)])
    assert updater.calls == []
