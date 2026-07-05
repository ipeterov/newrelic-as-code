from newrelic_as_code import Dashboard, NrqlQuery, Page, Variable, Widget


def test_nrql_query_serialization():
    q = NrqlQuery(query="SELECT count(*) FROM Transaction", account_ids=[42])
    assert q.as_nr_dict() == {
        "accountIds": [42],
        "query": "SELECT count(*) FROM Transaction",
    }


def test_nrql_query_defaults_to_empty_accounts():
    # Empty by default so the updater can inject its own account id.
    assert NrqlQuery(query="SELECT 1").as_nr_dict()["accountIds"] == []


def test_widget_serialization_with_query():
    w = Widget(
        title="Throughput",
        visualization="viz.line",
        column=1,
        row=2,
        queries=[NrqlQuery(query="SELECT 1", account_ids=[7])],
        raw_configuration={"legend": {"enabled": True}},
    )
    d = w.as_nr_dict()
    assert d["title"] == "Throughput"
    assert d["layout"] == {"column": 1, "row": 2, "width": 4, "height": 3}
    assert d["visualization"] == {"id": "viz.line"}
    # raw_configuration is merged, with nrqlQueries prepended.
    assert d["rawConfiguration"]["nrqlQueries"] == [{"accountIds": [7], "query": "SELECT 1"}]
    assert d["rawConfiguration"]["legend"] == {"enabled": True}


def test_query_less_widget_omits_nrql_queries():
    w = Widget(
        title="",
        visualization="viz.markdown",
        column=1,
        row=1,
        queries=[],
        raw_configuration={"text": "hello"},
    )
    raw = w.as_nr_dict()["rawConfiguration"]
    assert "nrqlQueries" not in raw
    assert raw == {"text": "hello"}


def test_variable_serialization():
    v = Variable(name="env", title="Environment", values=["prod", "stg"], default="prod")
    d = v.as_nr_dict()
    assert d["name"] == "env"
    assert d["type"] == "ENUM"
    assert d["replacementStrategy"] == "STRING"
    assert d["items"] == [
        {"title": None, "value": "prod"},
        {"title": None, "value": "stg"},
    ]
    assert d["defaultValues"] == [{"value": {"string": "prod"}}]


def test_dashboard_serialization_and_variables():
    page = Page(name="Overview", widgets=[])
    without = Dashboard(name="D", pages=[page])
    assert "variables" not in without.as_nr_dict()

    with_vars = Dashboard(
        name="D",
        pages=[page],
        variables=[Variable(name="env", title="Env", values=["prod"], default="prod")],
    )
    payload = with_vars.as_nr_dict()
    assert payload["name"] == "D"
    assert payload["permissions"] == "PUBLIC_READ_WRITE"
    assert len(payload["variables"]) == 1
