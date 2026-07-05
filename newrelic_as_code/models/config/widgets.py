"""
Per-visualization ``rawConfiguration`` config models.

Each config models the keys valid for one viz type, folding in ``nrqlQueries``
(the JSON puts the queries inside rawConfiguration, not on the widget). These are
the payloads the ``*Widget`` classes in ``models/widget.py`` expose. Every config
inherits ``raw`` (the escape hatch) from ``NrConfigModel``.

Field coverage is ported from New Relic's Terraform provider (see CLAUDE.md).
Anything not modeled here is still settable via ``raw={...}``.
"""

from ..base import NrConfigModel
from ..query import NrqlQuery
from .common import (
    BillboardThreshold,
    Colors,
    DataFormat,
    Facet,
    InitialSorting,
    Legend,
    LineThresholds,
    NullValues,
    TableThreshold,
    Tooltip,
    Units,
    YAxisLeft,
    YAxisRight,
)


class _QueryConfig(NrConfigModel):
    """Shared base for every query-backed viz config."""

    nrql_queries: list[NrqlQuery]
    platform_options: dict | None = None


class LineConfig(_QueryConfig):
    legend: Legend | None = None
    units: Units | None = None
    colors: Colors | None = None
    null_values: NullValues | None = None
    facet: Facet | None = None
    tooltip: Tooltip | None = None
    y_axis_left: YAxisLeft | None = None
    y_axis_right: YAxisRight | None = None
    thresholds: LineThresholds | None = None


class AreaConfig(_QueryConfig):
    legend: Legend | None = None
    units: Units | None = None
    colors: Colors | None = None
    null_values: NullValues | None = None
    facet: Facet | None = None
    tooltip: Tooltip | None = None
    y_axis_left: YAxisLeft | None = None
    thresholds: LineThresholds | None = None


class BarConfig(_QueryConfig):
    legend: Legend | None = None
    units: Units | None = None
    colors: Colors | None = None
    facet: Facet | None = None
    filter_current_dashboard: bool | None = None
    linked_entity_guids: list[str] | None = None


class StackedBarConfig(_QueryConfig):
    legend: Legend | None = None
    units: Units | None = None
    colors: Colors | None = None
    facet: Facet | None = None


class PieConfig(_QueryConfig):
    legend: Legend | None = None
    colors: Colors | None = None
    facet: Facet | None = None
    filter_current_dashboard: bool | None = None
    linked_entity_guids: list[str] | None = None


class BillboardConfig(_QueryConfig):
    thresholds: list[BillboardThreshold] | None = None
    data_format: list[DataFormat] | None = None


class TableConfig(_QueryConfig):
    thresholds: list[TableThreshold] | None = None
    initial_sorting: InitialSorting | None = None
    data_format: list[DataFormat] | None = None
    filter_current_dashboard: bool | None = None
    linked_entity_guids: list[str] | None = None


class HeatmapConfig(_QueryConfig):
    legend: Legend | None = None
    colors: Colors | None = None
    facet: Facet | None = None
    filter_current_dashboard: bool | None = None
    linked_entity_guids: list[str] | None = None


class HistogramConfig(_QueryConfig):
    colors: Colors | None = None
    facet: Facet | None = None


class JsonConfig(_QueryConfig):
    pass


class FunnelConfig(_QueryConfig):
    pass


class BulletConfig(_QueryConfig):
    limit: float | None = None


class MarkdownConfig(NrConfigModel):
    """Markdown is the one viz with no query — it renders ``text``."""

    text: str
