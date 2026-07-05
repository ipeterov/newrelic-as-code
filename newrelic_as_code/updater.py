"""
Reconciles New Relic with resource definitions in code.

Config lives in code; the live state in the New Relic account is inspected, then
resources are created/updated/deleted to match. New Relic itself is the state
store — managed entities are found by a ``managed-by`` tag, so there is nothing
to persist between runs.

``NerdGraphClient`` is the thin API transport; ``NewRelicUpdater.sync()``
reconciles everything. The reconcile core (``_reconcile``) is resource-agnostic:
find-by-managed-tag, create/update/delete-orphaned, refuse-to-clobber-unmanaged,
dry-run. Dashboards use it today; alert policies/conditions can be added as more
``sync_*`` steps that call the same core with alert-specific find/create/update/
delete callables — without reshaping the logic here.
"""

from collections.abc import Callable

import requests
from requests.adapters import HTTPAdapter, Retry

from .models import Dashboard
from .utils import echo


# Region NerdGraph endpoints. Default is US; the EU data center uses a separate
# host. Pass a full URL to ``NewRelicUpdater(endpoint=...)`` for anything else.
US_ENDPOINT = "https://api.newrelic.com/graphql"
EU_ENDPOINT = "https://api.eu.newrelic.com/graphql"

DEFAULT_MANAGED_TAG_KEY = "managed-by"


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


class NewRelicUpdater:
    """Reconciles New Relic with the code definitions.

    ``sync()`` is the single entry point. It reconciles dashboards today; alert
    policies/conditions can be added as more ``_sync_*`` steps that reuse
    ``_reconcile``.
    """

    def __init__(
        self,
        account_id: int,
        api_key: str,
        endpoint: str = US_ENDPOINT,
        managed_tag_key: str = DEFAULT_MANAGED_TAG_KEY,
        managed_tag_value: str = "newrelic-as-code",
        dry_run: bool = False,
    ):
        self.account_id = account_id
        self.managed_tag_key = managed_tag_key
        self.managed_tag_value = managed_tag_value
        self.client = NerdGraphClient(api_key, endpoint, dry_run)

    def sync(self, dashboards: list[Dashboard]) -> None:
        if self.client.dry_run:
            echo("Dry run — no changes will be applied")
        self._sync_dashboards(dashboards)
        echo("OK")

    # -- Generic reconcile core ----------------------------------------------

    def _reconcile(
        self,
        kind: str,
        entity_type: str,
        defined: dict[str, object],
        create: Callable[[object], None],
        update: Callable[[str, object], None],
        delete: Callable[[str], None],
    ) -> None:
        """Reconcile a set of managed resources of one ``entity_type``.

        ``defined`` maps resource name -> the resource object to apply. For each,
        we look up the existing managed entity (refusing to clobber a same-named
        unmanaged one), then create or update. Finally, any managed entity of
        this type no longer in ``defined`` is deleted as orphaned.

        Resource-agnostic: dashboards pass their find/create/update/delete;
        alerts can pass their own without reshaping this logic.
        """
        for name, resource in defined.items():
            existing = self._find_entity(name, entity_type)
            if existing:
                self.client.mutate(
                    f"update “{name}”",
                    lambda r=resource, g=existing["guid"]: update(g, r),
                )
            else:
                self.client.mutate(f"create “{name}”", lambda r=resource: create(r))

        for entity in self._managed_entities(entity_type):
            if entity["name"] not in defined:
                self.client.mutate(
                    f"delete orphaned {kind} “{entity['name']}”",
                    lambda g=entity["guid"]: delete(g),
                )

    # language=graphql
    _SEARCH = """
    query ($query: String!) {
      actor {
        entitySearch(query: $query) {
          results {
            entities {
              guid
              name
              tags {
                key
                values
              }
            }
          }
        }
      }
    }
    """

    def _managed_entities(self, entity_type: str) -> list[dict]:
        """All entities of ``entity_type`` in the account tagged as managed by us."""
        query = (
            f"type = '{entity_type}' AND accountId = {self.account_id} "
            f"AND tags.`{self.managed_tag_key}` = '{self.managed_tag_value}'"
        )
        data = self.client.call(self._SEARCH, {"query": query})
        return data["actor"]["entitySearch"]["results"]["entities"]

    def _find_entity(self, name: str, entity_type: str) -> dict | None:
        """The managed entity of ``entity_type`` named ``name``, or None.

        Raises if a same-named entity exists but is NOT managed by us — we must
        never clobber a hand-built resource.
        """
        query = f"name = '{name}' AND type = '{entity_type}' AND accountId = {self.account_id}"
        data = self.client.call(self._SEARCH, {"query": query})
        entities = data["actor"]["entitySearch"]["results"]["entities"]
        # entitySearch matches substrings; keep only exact-name matches.
        entities = [e for e in entities if e["name"] == name]
        if not entities:
            return None
        if len(entities) > 1:
            raise NewRelicUpdaterError(
                f"Multiple {entity_type} entities named '{name}' found — refusing to "
                "guess. Resolve the duplicate in New Relic first."
            )
        entity = entities[0]
        tags = {t["key"]: t["values"] for t in entity.get("tags") or []}
        if self.managed_tag_value not in tags.get(self.managed_tag_key, []):
            raise NewRelicUpdaterError(
                f"A {entity_type} named '{name}' exists but is not managed by this tool "
                f"(missing tag {self.managed_tag_key}={self.managed_tag_value}). Refusing "
                "to overwrite it. Rename or delete it, or tag it manually to adopt it."
            )
        return entity

    # -- Dashboards -----------------------------------------------------------

    def _sync_dashboards(self, dashboards: list[Dashboard]) -> None:
        """Upsert defined dashboards, then delete managed ones no longer defined."""
        defined = {d.name: d for d in dashboards}
        self._reconcile(
            kind="dashboard",
            entity_type="DASHBOARD",
            defined=defined,
            create=self._create_dashboard,
            update=self._update_dashboard,
            delete=self._delete_dashboard,
        )

    def _dashboard_input(self, dashboard: Dashboard) -> dict:
        """Serialize a dashboard, injecting our account id into account-less queries."""
        payload = dashboard.as_nr_dict()
        for page in payload["pages"]:
            for widget in page["widgets"]:
                for nrql in widget["rawConfiguration"].get("nrqlQueries", []):
                    if not nrql["accountIds"]:
                        nrql["accountIds"] = [self.account_id]
        return payload

    # language=graphql
    _CREATE = """
    mutation ($accountId: Int!, $dashboard: DashboardInput!) {
      dashboardCreate(accountId: $accountId, dashboard: $dashboard) {
        entityResult {
          guid
        }
        errors {
          description
          type
        }
      }
    }
    """

    # language=graphql
    _TAG = """
    mutation ($guid: EntityGuid!, $tags: [TaggingTagInput!]!) {
      taggingAddTagsToEntity(guid: $guid, tags: $tags) {
        errors {
          message
          type
        }
      }
    }
    """

    def _create_dashboard(self, dashboard: Dashboard) -> None:
        data = self.client.call(
            self._CREATE,
            {"accountId": self.account_id, "dashboard": self._dashboard_input(dashboard)},
        )
        result = data["dashboardCreate"]
        if result["errors"]:
            raise NewRelicUpdaterError(f"dashboardCreate: {result['errors']}")
        guid = result["entityResult"]["guid"]
        # Tag it so future runs recognize it as ours.
        tag_data = self.client.call(
            self._TAG,
            {
                "guid": guid,
                "tags": [{"key": self.managed_tag_key, "values": [self.managed_tag_value]}],
            },
        )
        if tag_data["taggingAddTagsToEntity"]["errors"]:
            raise NewRelicUpdaterError(
                f"taggingAddTagsToEntity: {tag_data['taggingAddTagsToEntity']['errors']}"
            )

    # language=graphql
    _UPDATE = """
    mutation ($guid: EntityGuid!, $dashboard: DashboardInput!) {
      dashboardUpdate(guid: $guid, dashboard: $dashboard) {
        entityResult {
          guid
        }
        errors {
          description
          type
        }
      }
    }
    """

    def _update_dashboard(self, guid: str, dashboard: Dashboard) -> None:
        data = self.client.call(
            self._UPDATE, {"guid": guid, "dashboard": self._dashboard_input(dashboard)}
        )
        result = data["dashboardUpdate"]
        if result["errors"]:
            raise NewRelicUpdaterError(f"dashboardUpdate: {result['errors']}")

    # language=graphql
    _DELETE = """
    mutation ($guid: EntityGuid!) {
      dashboardDelete(guid: $guid) {
        status
        errors {
          description
          type
        }
      }
    }
    """

    def _delete_dashboard(self, guid: str) -> None:
        data = self.client.call(self._DELETE, {"guid": guid})
        result = data["dashboardDelete"]
        if result["errors"]:
            raise NewRelicUpdaterError(f"dashboardDelete: {result['errors']}")
