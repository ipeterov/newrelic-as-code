"""
Thin New Relic NerdGraph API transport.

``NerdGraphClient`` wraps a single ``requests`` session with retry/backoff and a
dry-run gate. It knows nothing about dashboards or reconcile logic — it just
POSTs GraphQL and reports what a mutation would do. The reconcile logic lives in
``updater.py`` and drives this client.
"""

from collections.abc import Callable

import requests
from requests.adapters import HTTPAdapter, Retry

from .utils import echo


# Region NerdGraph endpoints. Default is US; the EU data center uses a separate
# host. Pass a full URL to ``NewRelicUpdater(endpoint=...)`` for anything else.
US_ENDPOINT = "https://api.newrelic.com/graphql"
EU_ENDPOINT = "https://api.eu.newrelic.com/graphql"


class NewRelicUpdaterError(Exception):
    """Raised when a NerdGraph call fails or the live state is ambiguous."""


class NerdGraphClient:
    """Thin New Relic NerdGraph API client with a dry-run gate."""

    def __init__(self, api_key: str, endpoint: str = US_ENDPOINT, dry_run: bool = False):
        self.api_key = api_key
        self.endpoint = endpoint
        self.dry_run = dry_run
        # NerdGraph occasionally responds slowly or with a transient 5xx. Retry
        # with backoff so a blip doesn't fail the run. NerdGraph mutations are
        # idempotent for us (create/update/delete by name+tag), so retrying a
        # POST is safe.
        self.session = requests.Session()
        retry = Retry(
            total=4,
            backoff_factor=2,  # 0s, 2s, 4s, 8s between attempts
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def call(self, query: str, variables: dict) -> dict:
        response = self.session.post(
            self.endpoint,
            json={"query": query, "variables": variables},
            headers={"API-Key": self.api_key},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise NewRelicUpdaterError(f"NerdGraph errors: {payload['errors']}")
        return payload["data"]

    def mutate(self, action: str, do: Callable[[], object]) -> object | None:
        """Run a mutation, or just print what it would do in dry-run mode."""
        if self.dry_run:
            echo(f"Would {action}")
            return None
        echo(action[0].upper() + action[1:])
        return do()
