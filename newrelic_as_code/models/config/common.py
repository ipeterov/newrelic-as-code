"""
Shared ``rawConfiguration`` option models.

These are the sub-objects that recur across widget types (yAxis, legend, units,
colors, thresholds, ...). Each per-visualization config in ``widgets.py`` picks
the ones its viz supports. Keys mirror the camelCase JSON New Relic's Terraform
provider produces (see CLAUDE.md for the reference).
"""

from typing import Literal

from ..base import NrModel


Severity = Literal["warning", "critical", "success", "unavailable"]


class _FromRange(NrModel):
    """Mixin for threshold ranges: ``from`` is a Python keyword, so the field is
    ``from_`` and is emitted as ``from`` in the JSON."""

    def as_nr_dict(self) -> dict:
        result = super().as_nr_dict()
        if "from_" in result:
            result["from"] = result.pop("from_")
        return result


class YAxisLeft(NrModel):
    zero: bool | None = None
    min: float | None = None
    max: float | None = None


class YAxisRightSeries(NrModel):
    name: str


class YAxisRight(NrModel):
    zero: bool | None = None
    min: float | None = None
    max: float | None = None
    series: list[YAxisRightSeries] | None = None


class Legend(NrModel):
    enabled: bool | None = None


class Facet(NrModel):
    show_other_series: bool | None = None


class Tooltip(NrModel):
    mode: str


class RefreshRate(NrModel):
    frequency: int


class PlatformOptions(NrModel):
    ignore_time_range: bool | None = None


class UnitOverride(NrModel):
    unit: str
    series_name: str | None = None


class Units(NrModel):
    unit: str | None = None
    series_overrides: list[UnitOverride] | None = None


class ColorOverride(NrModel):
    color: str
    series_name: str | None = None


class Colors(NrModel):
    color: str | None = None
    series_overrides: list[ColorOverride] | None = None


class NullValueOverride(NrModel):
    null_value: str
    series_name: str | None = None


class NullValues(NrModel):
    null_value: str | None = None
    series_overrides: list[NullValueOverride] | None = None


class DataFormat(NrModel):
    name: str
    type: str | None = None
    format: str | None = None
    precision: int | None = None


class InitialSorting(NrModel):
    direction: Literal["asc", "desc"]
    name: str


# --- thresholds differ by visualization ---------------------------------------


class LineThreshold(_FromRange):
    """A single reference line on a line/area chart (``from == to`` draws one)."""

    name: str | None = None
    from_: float | None = None
    to: float | None = None
    severity: Severity | None = None


class LineThresholds(NrModel):
    """Line/area threshold block: ``{isLabelVisible, thresholds: [...]}``."""

    thresholds: list[LineThreshold]
    is_label_visible: bool | None = None


class BillboardThreshold(NrModel):
    """A billboard threshold: colors the number when it crosses ``value``."""

    alert_severity: Severity
    value: float


class TableThreshold(_FromRange):
    """A table cell threshold, scoped to a column."""

    column_name: str | None = None
    from_: float | None = None
    to: float | None = None
    severity: Severity | None = None
