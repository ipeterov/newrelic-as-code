"""Define New Relic dashboards as code and reconcile them to an account."""

from importlib.metadata import PackageNotFoundError, version

from .client import (
    EU_ENDPOINT,
    US_ENDPOINT,
    NerdGraphClient,
    NewRelicUpdaterError,
)
from .models import Dashboard, NrqlQuery, Page, Variable, Visualization, Widget
from .updater import NewRelicUpdater
from .utils import echo


try:
    # pyproject.toml is the single source of truth; read it from the installed
    # package metadata rather than duplicating the number here.
    __version__ = version("newrelic-as-code")
except PackageNotFoundError:  # not installed (e.g. running from a source tree)
    __version__ = "0.0.0.dev0"

__all__ = [
    "EU_ENDPOINT",
    "US_ENDPOINT",
    "Dashboard",
    "NerdGraphClient",
    "NewRelicUpdater",
    "NewRelicUpdaterError",
    "NrqlQuery",
    "Page",
    "Variable",
    "Visualization",
    "Widget",
    "echo",
]
