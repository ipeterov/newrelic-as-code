"""Define New Relic dashboards as code and reconcile them to an account.

This module is the package's public API. Everything a consumer needs is
importable straight from ``newrelic_as_code``; the internal module split
(``models/``, ``client``, ``updater``) is an implementation detail. Adding a
public name means importing it here and listing it in ``__all__`` — this file is
the single source of what the package exposes.
"""

from importlib.metadata import PackageNotFoundError, version

from .client import EU_ENDPOINT, US_ENDPOINT, NerdGraphClient, NewRelicUpdaterError
from .models.config.common import (
    BillboardThreshold,
    ColorOverride,
    Colors,
    DataFormat,
    Facet,
    InitialSorting,
    Legend,
    LineThreshold,
    LineThresholds,
    NullValueOverride,
    NullValues,
    PlatformOptions,
    RefreshRate,
    Severity,
    TableThreshold,
    Tooltip,
    UnitOverride,
    Units,
    YAxisLeft,
    YAxisRight,
    YAxisRightSeries,
)
from .models.dashboard import AnyWidget, Dashboard, Page, Permissions
from .models.query import NrqlQuery
from .models.variable import (
    ReplacementStrategy,
    Variable,
    VariableEnumItem,
    VariableNrqlQuery,
    VariableOptions,
    VariableType,
)
from .models.widget import (
    AreaWidget,
    BarWidget,
    BillboardWidget,
    BulletWidget,
    FunnelWidget,
    HeatmapWidget,
    HistogramWidget,
    JsonWidget,
    Layout,
    LineWidget,
    Link,
    MarkdownWidget,
    PieWidget,
    StackedBarWidget,
    TableWidget,
    Widget,
)
from .updater import NewRelicUpdater
from .utils import echo


try:
    # pyproject.toml is the single source of truth; read it from the installed
    # package metadata rather than duplicating the number here.
    __version__ = version("newrelic-as-code")
except PackageNotFoundError:  # not installed (e.g. running from a source tree)
    __version__ = "0.0.0.dev0"


__all__ = [
    # -- reconcile --------------------------------------------------------------
    "NewRelicUpdater",
    "NerdGraphClient",
    "NewRelicUpdaterError",
    "US_ENDPOINT",
    "EU_ENDPOINT",
    "echo",
    # -- dashboard envelope -----------------------------------------------------
    "Dashboard",
    "Page",
    "Permissions",
    "Layout",
    "Link",
    "NrqlQuery",
    "AnyWidget",
    # -- widgets (one per visualization) ---------------------------------------
    "Widget",  # generic escape hatch
    "AreaWidget",
    "BarWidget",
    "BillboardWidget",
    "BulletWidget",
    "FunnelWidget",
    "HeatmapWidget",
    "HistogramWidget",
    "JsonWidget",
    "LineWidget",
    "MarkdownWidget",
    "PieWidget",
    "StackedBarWidget",
    "TableWidget",
    # -- widget config options --------------------------------------------------
    "Legend",
    "Facet",
    "Tooltip",
    "RefreshRate",
    "PlatformOptions",
    "Units",
    "UnitOverride",
    "Colors",
    "ColorOverride",
    "NullValues",
    "NullValueOverride",
    "DataFormat",
    "InitialSorting",
    "YAxisLeft",
    "YAxisRight",
    "YAxisRightSeries",
    "LineThreshold",
    "LineThresholds",
    "BillboardThreshold",
    "TableThreshold",
    "Severity",
    # -- variables --------------------------------------------------------------
    "Variable",
    "VariableEnumItem",
    "VariableNrqlQuery",
    "VariableOptions",
    "VariableType",
    "ReplacementStrategy",
]
