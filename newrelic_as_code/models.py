"""
New Relic dashboards as code.

Typed pydantic models that each render to the JSON shape the New Relic
NerdGraph API expects via an ``as_nr_dict()`` method. Compose dashboards
declaratively and reconcile them with ``NewRelicUpdater``.

NerdGraph dashboard input reference:
https://docs.newrelic.com/docs/apis/nerdgraph/examples/nerdgraph-dashboards/
"""

from typing import Literal

from pydantic import BaseModel, Field


Visualization = Literal[
    "viz.line",
    "viz.area",
    "viz.bar",
    "viz.pie",
    "viz.table",
    "viz.billboard",
    "viz.gauge",
    "viz.markdown",
]


class NrqlQuery(BaseModel):
    query: str
    # Accounts this query runs against. Leave empty to let ``NewRelicUpdater``
    # fill in its own account id at reconcile time; set it explicitly to query
    # across accounts (or a different account than the one you reconcile to).
    account_ids: list[int] = Field(default_factory=list)

    def as_nr_dict(self) -> dict:
        return {
            "accountIds": self.account_ids,
            "query": self.query,
        }


class Widget(BaseModel):
    title: str
    visualization: Visualization
    queries: list[NrqlQuery]
    column: int
    row: int
    width: int = 4
    height: int = 3
    # Extra keys merged into rawConfiguration (units, colors, markers, yAxis,
    # gaugeSettings, ...). Kept as a free dict so we don't have to model every
    # New Relic chart option.
    raw_configuration: dict = Field(default_factory=dict)

    def as_nr_dict(self) -> dict:
        raw: dict = dict(self.raw_configuration)
        # Query-backed widgets carry nrqlQueries; query-less widgets (e.g.
        # markdown, which uses `text`) must not emit an empty nrqlQueries list.
        if self.queries:
            raw = {"nrqlQueries": [q.as_nr_dict() for q in self.queries], **raw}
        return {
            "title": self.title,
            "layout": {
                "column": self.column,
                "row": self.row,
                "width": self.width,
                "height": self.height,
            },
            "linkedEntityGuids": None,
            "visualization": {"id": self.visualization},
            "rawConfiguration": raw,
        }


class Variable(BaseModel):
    name: str
    title: str
    values: list[str]
    default: str
    replacement_strategy: Literal["DEFAULT", "STRING", "NUMBER", "IDENTIFIER"] = "STRING"

    def as_nr_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "type": "ENUM",
            "isMultiSelection": False,
            "replacementStrategy": self.replacement_strategy,
            "items": [{"title": None, "value": v} for v in self.values],
            "defaultValues": [{"value": {"string": self.default}}],
            "nrqlQuery": None,
            "options": {"hiddenOnVariablesBar": False, "excluded": False},
        }


class Page(BaseModel):
    name: str
    widgets: list[Widget]
    description: str | None = None

    def as_nr_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "widgets": [w.as_nr_dict() for w in self.widgets],
        }


class Dashboard(BaseModel):
    name: str
    pages: list[Page]
    description: str | None = None
    variables: list[Variable] = Field(default_factory=list)
    permissions: Literal["PRIVATE", "PUBLIC_READ_ONLY", "PUBLIC_READ_WRITE"] = "PUBLIC_READ_WRITE"

    def as_nr_dict(self) -> dict:
        """Render to the ``DashboardInput`` shape for dashboardCreate/dashboardUpdate."""
        result: dict = {
            "name": self.name,
            "description": self.description,
            "permissions": self.permissions,
            "pages": [p.as_nr_dict() for p in self.pages],
        }
        if self.variables:
            result["variables"] = [v.as_nr_dict() for v in self.variables]
        return result
