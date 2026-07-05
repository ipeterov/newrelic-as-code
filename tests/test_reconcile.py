"""Reconcile decision-logic tests against a fake NerdGraph.

We stub only ``NerdGraphClient.call`` (the transport) so the real
``_reconcile`` / ``_find_entity`` / ``_managed_entities`` / dashboard mutation
code runs and we can assert which create/update/delete calls it decides to make.
"""

import pytest

from newrelic_as_code import Dashboard, NewRelicUpdater, NewRelicUpdaterError, Page


TAG_KEY = "managed-by"
TAG_VALUE = "test-deploy"


def _dashboard(name):
    return Dashboard(name=name, pages=[Page(name="p", widgets=[])])


def _entity(name, managed=True):
    tags = [{"key": TAG_KEY, "values": [TAG_VALUE]}] if managed else []
    return {"guid": f"guid-{name}", "name": name, "tags": tags}


class FakeUpdater(NewRelicUpdater):
    """Updater whose NerdGraph transport is a scripted fake.

    ``existing`` is the set of entities the account currently holds (by name).
    Every mutation is recorded in ``self.calls`` as (op, name-or-guid).
    """

    def __init__(self, existing, **kwargs):
        super().__init__(
            account_id=1,
            api_key="k",
            managed_tag_key=TAG_KEY,
            managed_tag_value=TAG_VALUE,
            **kwargs,
        )
        self._existing = {e["name"]: e for e in existing}
        self.calls = []
        self.client.call = self._fake_call

    def _fake_call(self, query, variables):
        if "entitySearch" in query:
            nrql = variables["query"]
            if f"tags.`{TAG_KEY}`" in nrql:
                # _managed_entities: all managed entities in the account.
                entities = [e for e in self._existing.values() if _is_managed(e)]
            else:
                # _find_entity: substring name match (mirrors real entitySearch).
                wanted = nrql.split("name = '", 1)[1].split("'", 1)[0]
                entities = [e for e in self._existing.values() if wanted in e["name"]]
            return {"actor": {"entitySearch": {"results": {"entities": entities}}}}
        if "dashboardCreate" in query:
            self.calls.append(("create", variables["dashboard"]["name"]))
            return {"dashboardCreate": {"entityResult": {"guid": "new"}, "errors": None}}
        if "taggingAddTagsToEntity" in query:
            return {"taggingAddTagsToEntity": {"errors": None}}
        if "dashboardUpdate" in query:
            self.calls.append(("update", variables["guid"]))
            return {
                "dashboardUpdate": {"entityResult": {"guid": variables["guid"]}, "errors": None}
            }
        if "dashboardDelete" in query:
            self.calls.append(("delete", variables["guid"]))
            return {"dashboardDelete": {"status": "SUCCESS", "errors": None}}
        raise AssertionError(f"unexpected query: {query}")


def _is_managed(entity):
    tags = {t["key"]: t["values"] for t in entity.get("tags") or []}
    return TAG_VALUE in tags.get(TAG_KEY, [])


def test_creates_when_absent():
    updater = FakeUpdater(existing=[])
    updater.sync([_dashboard("New")])
    assert updater.calls == [("create", "New")]


def test_updates_when_managed_exists():
    updater = FakeUpdater(existing=[_entity("Existing")])
    updater.sync([_dashboard("Existing")])
    assert updater.calls == [("update", "guid-Existing")]


def test_deletes_orphaned_managed_dashboard():
    # 'Old' is managed but not in the declared set -> deleted.
    updater = FakeUpdater(existing=[_entity("Old")])
    updater.sync([])
    assert updater.calls == [("delete", "guid-Old")]


def test_refuses_to_clobber_unmanaged():
    updater = FakeUpdater(existing=[_entity("Hand-built", managed=False)])
    with pytest.raises(NewRelicUpdaterError, match="not managed by this tool"):
        updater.sync([_dashboard("Hand-built")])
    assert updater.calls == []


def test_refuses_ambiguous_duplicate():
    updater = FakeUpdater(existing=[])
    updater._existing = {
        "A": _entity("Dup"),
        "B": {"guid": "guid-2", "name": "Dup", "tags": []},
    }
    with pytest.raises(NewRelicUpdaterError, match="refusing to guess"):
        updater.sync([_dashboard("Dup")])


def test_dry_run_makes_no_mutations():
    updater = FakeUpdater(existing=[_entity("Existing")], dry_run=True)
    updater.sync([_dashboard("Existing"), _dashboard("New")])
    assert updater.calls == []


def test_account_id_injected_into_account_less_queries():
    from newrelic_as_code import Layout, LineWidget, NrqlQuery

    dash = Dashboard(
        name="D",
        pages=[
            Page(
                name="p",
                widgets=[
                    LineWidget(
                        title="w",
                        layout=Layout(column=1, row=1),
                        nrql_queries=[
                            NrqlQuery(query="SELECT 1"),  # no account -> injected
                            NrqlQuery(query="SELECT 2", account_ids=[999]),  # kept
                        ],
                    )
                ],
            )
        ],
    )
    updater = FakeUpdater(existing=[])
    payload = updater._dashboard_input(dash)
    nrqls = payload["pages"][0]["widgets"][0]["rawConfiguration"]["nrqlQueries"]
    assert nrqls[0]["accountId"] == 1  # singular, injected
    assert nrqls[1]["accountIds"] == [999]  # explicit multi-account kept
