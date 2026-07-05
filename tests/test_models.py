from newrelic_as_code import (
    AreaWidget,
    BillboardThreshold,
    BillboardWidget,
    ColorOverride,
    Colors,
    Dashboard,
    Layout,
    Legend,
    LineThreshold,
    LineThresholds,
    LineWidget,
    MarkdownWidget,
    NrqlQuery,
    Page,
    Variable,
    VariableNrqlQuery,
    Widget,
    YAxisLeft,
)


def _q(query="SELECT 1"):
    return NrqlQuery(query=query)


def test_nrql_query_account_forms():
    assert NrqlQuery(query="SELECT 1").as_nr_dict() == {"query": "SELECT 1"}
    assert NrqlQuery(query="S", account_id=7).as_nr_dict() == {"query": "S", "accountId": 7}
    assert NrqlQuery(query="S", account_ids=[7, 8]).as_nr_dict() == {
        "query": "S",
        "accountIds": [7, 8],
    }


def test_line_widget_envelope_and_config():
    w = LineWidget(
        title="Throughput",
        layout=Layout(column=1, row=2),
        nrql_queries=[_q()],
        legend=Legend(enabled=True),
        y_axis_left=YAxisLeft(zero=True),
    )
    d = w.as_nr_dict()
    assert d["title"] == "Throughput"
    assert d["layout"] == {"column": 1, "row": 2, "width": 4, "height": 3}
    assert d["visualization"] == {"id": "viz.line"}
    raw = d["rawConfiguration"]
    assert raw["nrqlQueries"] == [{"query": "SELECT 1"}]
    assert raw["legend"] == {"enabled": True}
    assert raw["yAxisLeft"] == {"zero": True}


def test_camelcase_and_none_omitted():
    # colors.series_overrides -> seriesOverrides; unset fields dropped.
    w = AreaWidget(
        layout=Layout(column=1, row=1),
        nrql_queries=[_q()],
        colors=Colors(series_overrides=[ColorOverride(color="#fff", series_name="A")]),
    )
    raw = w.as_nr_dict()["rawConfiguration"]
    assert raw["colors"] == {"seriesOverrides": [{"color": "#fff", "seriesName": "A"}]}
    assert "legend" not in raw  # unset -> omitted


def test_line_thresholds_from_keyword():
    w = LineWidget(
        layout=Layout(column=1, row=1),
        nrql_queries=[_q()],
        thresholds=LineThresholds(
            is_label_visible=True,
            thresholds=[LineThreshold(name="ceil", from_=6.0, to=6.0, severity="critical")],
        ),
    )
    t = w.as_nr_dict()["rawConfiguration"]["thresholds"]
    assert t["isLabelVisible"] is True
    # `from_` emitted as `from`.
    assert t["thresholds"][0] == {"name": "ceil", "from": 6.0, "to": 6.0, "severity": "critical"}


def test_billboard_thresholds():
    w = BillboardWidget(
        layout=Layout(column=1, row=1),
        nrql_queries=[_q()],
        thresholds=[BillboardThreshold(alert_severity="warning", value=50)],
    )
    raw = w.as_nr_dict()["rawConfiguration"]
    assert raw["thresholds"] == [{"alertSeverity": "warning", "value": 50.0}]


def test_markdown_widget_has_no_queries():
    w = MarkdownWidget(layout=Layout(column=1, row=1, width=12, height=1), text="hi")
    d = w.as_nr_dict()
    assert d["visualization"] == {"id": "viz.markdown"}
    assert d["rawConfiguration"] == {"text": "hi"}


def test_raw_escape_hatch_merges_over_typed():
    w = LineWidget(
        layout=Layout(column=1, row=1),
        nrql_queries=[_q()],
        legend=Legend(enabled=True),
        raw={"legend": {"enabled": False}, "customKey": 1},
    )
    raw = w.as_nr_dict()["rawConfiguration"]
    # raw wins on conflict, and adds unmodeled keys.
    assert raw["legend"] == {"enabled": False}
    assert raw["customKey"] == 1


def test_generic_widget_passes_raw_config_through():
    w = Widget(
        title="custom",
        layout=Layout(column=1, row=1),
        visualization="viz.bullet",
        raw_configuration={"nrqlQueries": [{"query": "SELECT 1"}], "limit": 100},
    )
    d = w.as_nr_dict()
    assert d["visualization"] == {"id": "viz.bullet"}
    assert d["rawConfiguration"] == {"nrqlQueries": [{"query": "SELECT 1"}], "limit": 100}


def test_widget_optional_envelope_fields():
    w = LineWidget(
        layout=Layout(column=1, row=1),
        nrql_queries=[_q()],
        description="tooltip text",
        linked_entity_guids=["GUID1"],
        id="widget-1",
    )
    d = w.as_nr_dict()
    assert d["description"] == "tooltip text"
    assert d["linkedEntityGuids"] == ["GUID1"]
    assert d["id"] == "widget-1"


def test_variable_enum_shorthand():
    v = Variable(name="env", title="Env", values=["prod", "stg"], default="prod")
    d = v.as_nr_dict()
    assert d["type"] == "ENUM"
    assert d["items"] == [{"title": None, "value": "prod"}, {"title": None, "value": "stg"}]
    assert d["defaultValues"] == [{"value": {"string": "prod"}}]


def test_variable_nrql_type():
    v = Variable(
        name="host",
        type="NRQL",
        nrql_query=VariableNrqlQuery(query="SELECT uniques(host) FROM T", account_ids=[1]),
        default_values=["a", "b"],
    )
    d = v.as_nr_dict()
    assert d["type"] == "NRQL"
    assert d["nrqlQuery"] == {"query": "SELECT uniques(host) FROM T", "accountIds": [1]}
    assert d["defaultValues"] == [{"value": {"string": "a"}}, {"value": {"string": "b"}}]


def test_dashboard_serialization_and_variables():
    page = Page(name="Overview", widgets=[])
    without = Dashboard(name="D", pages=[page])
    assert "variables" not in without.as_nr_dict()

    with_vars = Dashboard(
        name="D",
        pages=[page],
        variables=[Variable(name="env", values=["prod"], default="prod")],
    )
    payload = with_vars.as_nr_dict()
    assert payload["name"] == "D"
    assert payload["permissions"] == "PUBLIC_READ_WRITE"
    assert len(payload["variables"]) == 1
