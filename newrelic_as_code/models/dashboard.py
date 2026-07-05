"""Dashboard and Page — the top of the envelope."""

from typing import Any, Literal

from pydantic import ConfigDict

from .base import NrModel
from .variable import Variable
from .widget import Widget, _WidgetEnvelope


Permissions = Literal["PRIVATE", "PUBLIC_READ_ONLY", "PUBLIC_READ_WRITE"]

# Any widget: a typed ``*Widget`` (subclass of ``_WidgetEnvelope``) or the
# generic escape-hatch ``Widget``.
AnyWidget = _WidgetEnvelope | Widget


class Page(NrModel):
    name: str
    widgets: list[AnyWidget]
    description: str | None = None
    # Present on updates; None means "create a new page".
    guid: str | None = None

    # Widgets are a heterogeneous union of arbitrary widget subclasses; allow them.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def as_nr_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "widgets": [w.as_nr_dict() for w in self.widgets],
        }
        if self.guid is not None:
            result["guid"] = self.guid
        return result


class Dashboard(NrModel):
    name: str
    pages: list[Page]
    description: str | None = None
    variables: list[Variable] | None = None
    permissions: Permissions = "PUBLIC_READ_WRITE"

    def as_nr_dict(self) -> dict[str, Any]:
        """Render to the ``DashboardInput`` shape for dashboardCreate/dashboardUpdate."""
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "permissions": self.permissions,
            "pages": [p.as_nr_dict() for p in self.pages],
        }
        if self.variables:
            result["variables"] = [v.as_nr_dict() for v in self.variables]
        return result
