"""Dashboard template variables (the full NerdGraph variable machinery)."""

from typing import Any, Literal

from .base import NrModel
from .query import NrqlQuery


VariableType = Literal["ENUM", "NRQL", "STRING"]
ReplacementStrategy = Literal["DEFAULT", "STRING", "NUMBER", "IDENTIFIER"]


class VariableEnumItem(NrModel):
    value: str
    title: str | None = None


class VariableNrqlQuery(NrModel):
    """NRQL that supplies a variable's possible values (type ``NRQL``)."""

    query: str
    account_ids: list[int]


class VariableOptions(NrModel):
    excluded: bool | None = None
    hidden_on_variables_bar: bool | None = None
    ignore_time_range: bool | None = None
    show_apply_action: bool | None = None


class Variable(NrModel):
    """A dashboard-local template variable.

    Supports all three NerdGraph types: ``ENUM`` (fixed ``items``), ``NRQL``
    (values from ``nrql_query``), and ``STRING`` (free text). ``default`` is a
    convenience for the common single-default case; it renders to the
    ``defaultValues`` array NerdGraph expects.
    """

    name: str
    title: str | None = None
    type: VariableType = "ENUM"
    replacement_strategy: ReplacementStrategy = "STRING"
    is_multi_selection: bool = False
    values: list[str] | None = None
    items: list[VariableEnumItem] | None = None
    nrql_query: VariableNrqlQuery | None = None
    options: VariableOptions | None = None
    default: str | None = None
    default_values: list[str] | None = None

    def as_nr_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "type": self.type,
            "replacementStrategy": self.replacement_strategy,
            "isMultiSelection": self.is_multi_selection,
        }

        # `items` — explicit items win; otherwise derive from the `values` shorthand.
        if self.items is not None:
            result["items"] = [i.as_nr_dict() for i in self.items]
        elif self.values is not None:
            result["items"] = [{"title": None, "value": v} for v in self.values]

        if self.nrql_query is not None:
            result["nrqlQuery"] = self.nrql_query.as_nr_dict()
        if self.options is not None:
            result["options"] = self.options.as_nr_dict()

        # `defaultValues` — the list wins; else wrap the single `default`.
        defaults = self.default_values
        if defaults is None and self.default is not None:
            defaults = [self.default]
        if defaults is not None:
            result["defaultValues"] = [{"value": {"string": v}} for v in defaults]

        return result


# NrqlQuery is re-exported for callers building NRQL-typed variables' documents.
__all__ = [
    "NrqlQuery",
    "ReplacementStrategy",
    "Variable",
    "VariableEnumItem",
    "VariableNrqlQuery",
    "VariableOptions",
    "VariableType",
]
