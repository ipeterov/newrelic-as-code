"""
Widgets — the user-facing headline of the library.

The New Relic dashboard JSON has a flat widget envelope: a ``visualization.id``
string discriminator sitting beside a ``rawConfiguration`` bag whose valid keys
depend on that discriminator. Rather than make users pair a viz string with a
matching config object by hand (two sources of truth that can silently
disagree), each visualization is its own widget class — ``LineWidget``,
``BillboardWidget``, ... — that pins its ``visualization`` and exposes exactly
the fields valid for that viz. Mismatch is structurally impossible.

``Widget`` remains as a generic escape hatch: pass any ``visualization`` and a
``raw_configuration`` dict for a viz type without a dedicated class yet.

Every typed widget also accepts ``raw`` (merged over its typed config), so a
valid-but-unmodeled rawConfiguration key is always expressable.
"""

from typing import Any, ClassVar

from .base import NrModel
from .config import widgets as cfg


class Layout(NrModel):
    """A widget's position and size on the 12-column grid."""

    column: int
    row: int
    width: int = 4
    height: int = 3


class Link(NrModel):
    url: str


class _WidgetEnvelope(NrModel):
    """The fields common to every widget, independent of visualization."""

    title: str = ""
    layout: Layout
    description: str | None = None
    link: Link | None = None
    linked_entity_guids: list[str] | None = None
    # Present on updates; None means "create a new widget".
    id: str | None = None

    # Subclasses set these two.
    visualization: ClassVar[str]
    _config_type: ClassVar[type]

    def _config(self) -> NrModel:
        """Build the config model from this widget's own (flattened) fields."""
        field_names = self._config_type.model_fields
        data = {name: getattr(self, name) for name in field_names if hasattr(self, name)}
        return self._config_type(**data)

    def as_nr_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "title": self.title,
            "layout": self.layout.as_nr_dict(),
            "linkedEntityGuids": self.linked_entity_guids,
            "visualization": {"id": self.visualization},
            "rawConfiguration": self._config().as_nr_dict(),
        }
        if self.description is not None:
            result["description"] = self.description
        if self.link is not None:
            result["link"] = self.link.as_nr_dict()
        if self.id is not None:
            result["id"] = self.id
        return result


def _widget(name: str, viz: str, config_type: type) -> type:
    """Build a ``*Widget`` class: envelope fields + the config's fields, flat.

    The class inherits the config type (so its fields and ``raw`` escape hatch
    are available directly on the widget) and the envelope (title/layout/...).
    ``visualization`` is pinned, so it can never disagree with the config.
    """
    return type(
        name,
        (_WidgetEnvelope, config_type),
        {
            "__module__": __name__,
            "visualization": viz,
            "_config_type": config_type,
            "__doc__": f"Widget for the ``{viz}`` visualization.",
        },
    )


LineWidget = _widget("LineWidget", "viz.line", cfg.LineConfig)
AreaWidget = _widget("AreaWidget", "viz.area", cfg.AreaConfig)
BarWidget = _widget("BarWidget", "viz.bar", cfg.BarConfig)
StackedBarWidget = _widget("StackedBarWidget", "viz.stacked-bar", cfg.StackedBarConfig)
PieWidget = _widget("PieWidget", "viz.pie", cfg.PieConfig)
BillboardWidget = _widget("BillboardWidget", "viz.billboard", cfg.BillboardConfig)
TableWidget = _widget("TableWidget", "viz.table", cfg.TableConfig)
HeatmapWidget = _widget("HeatmapWidget", "viz.heatmap", cfg.HeatmapConfig)
HistogramWidget = _widget("HistogramWidget", "viz.histogram", cfg.HistogramConfig)
JsonWidget = _widget("JsonWidget", "viz.json", cfg.JsonConfig)
FunnelWidget = _widget("FunnelWidget", "viz.funnel", cfg.FunnelConfig)
BulletWidget = _widget("BulletWidget", "viz.bullet", cfg.BulletConfig)
MarkdownWidget = _widget("MarkdownWidget", "viz.markdown", cfg.MarkdownConfig)


class Widget(NrModel):
    """Generic escape-hatch widget: any visualization, raw config dict.

    Use a typed ``*Widget`` where one exists; reach for this for a visualization
    without a dedicated class, or when you want to hand-write the full
    ``rawConfiguration``.
    """

    title: str = ""
    layout: Layout
    visualization: str
    raw_configuration: dict[str, Any] = {}
    description: str | None = None
    link: Link | None = None
    linked_entity_guids: list[str] | None = None
    id: str | None = None

    def as_nr_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "title": self.title,
            "layout": self.layout.as_nr_dict(),
            "linkedEntityGuids": self.linked_entity_guids,
            "visualization": {"id": self.visualization},
            "rawConfiguration": self.raw_configuration,
        }
        if self.description is not None:
            result["description"] = self.description
        if self.link is not None:
            result["link"] = self.link.as_nr_dict()
        if self.id is not None:
            result["id"] = self.id
        return result
