"""
Reconciles New Relic with resource definitions in code.

Config lives in code; the live state in the New Relic account is inspected, then
resources are created/updated/deleted to match. New Relic itself is the state
store — managed entities are found by a ``managed-by`` tag, so there is nothing
to persist between runs.

The thin API transport is ``NerdGraphClient`` (see ``client.py``);
``NewRelicUpdater.sync()`` reconciles everything on top of it. The whole rollout
is two passes over the resource kinds, in dependency order (a resource only
ever references kinds that come before it):

1. create or update every defined resource, kind by kind;
2. delete every managed resource that is no longer defined, in reverse order —
   so nothing is deleted while something defined still references it.

The reconcile core (``_reconcile``) is resource-agnostic: given how to find the
live resources of one kind, it upserts the defined ones and queues the orphaned
ones for deletion.
"""

import warnings
from collections.abc import Callable, Iterable
from typing import Protocol, TypeVar

from .client import US_ENDPOINT, NerdGraphClient, NewRelicUpdaterError
from .models.base import NrModel, NrResource
from .models.dashboard import Dashboard
from .utils import echo


DEFAULT_MANAGED_TAG_KEY = "managed-by"


class _Named(Protocol):
    name: str


R = TypeVar("R", bound=_Named)
T = TypeVar("T", bound=NrResource)

# A queued deletion, run in the second pass of ``sync()``.
Delete = Callable[[], None]


class NewRelicUpdater:
    """Reconciles New Relic with the code definitions.

    ``sync()`` is the single entry point; it runs one ``_sync_*`` step per
    resource kind, each built on ``_reconcile``.
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

    def sync(
        self,
        resources: Iterable[NrResource] = (),
        *,
        dashboards: Iterable[Dashboard] | None = None,
    ) -> None:
        """Make the managed resources in the account exactly ``resources``.

        ``resources`` is the complete desired state: every resource passed, plus
        every resource those reference, is created or updated; every managed
        resource not among them is deleted.

        ``dashboards=`` is the pre-alerts spelling of the same thing, kept for
        backwards compatibility.
        """
        if dashboards is not None:
            warnings.warn(
                "sync(dashboards=...) is deprecated; pass them as sync([...]) instead",
                DeprecationWarning,
                stacklevel=2,
            )
            resources = [*resources, *dashboards]
        defined = _collect(resources)

        if self.client.dry_run:
            echo("Dry run — no changes will be applied")
        deletes: list[Delete] = []
        self._sync_dashboards(_of_type(defined, Dashboard), deletes)
        for delete in reversed(deletes):
            delete()
        echo("OK")

    # -- Generic reconcile core ----------------------------------------------

    def _reconcile(
        self,
        kind: str,
        defined: dict[str, R],
        find: Callable[[str], str | None],
        managed: Callable[[], Iterable[tuple[str, str]]],
        create: Callable[[R], str],
        update: Callable[[str, R], None],
        delete: Callable[[str], None],
        deletes: list[Delete],
    ) -> dict[str, str | None]:
        """Reconcile one set of managed resources of a single kind.

        ``defined`` maps resource name -> the resource object to apply. For
        each, ``find(name)`` returns the id of the existing managed resource (or
        None, or raises if it must not be touched); we update it or create a new
        one. Every ``(name, id)`` from ``managed()`` that is no longer in
        ``defined`` is queued onto ``deletes`` as orphaned.

        Returns name -> id for every defined resource: the existing id for
        updates, ``create``'s result for creates (None for a dry-run create).
        """
        ids: dict[str, str | None] = {}
        for name, resource in defined.items():
            existing = find(name)
            if existing:
                self.client.mutate(
                    f"update {kind} “{name}”",
                    lambda r=resource, i=existing: update(i, r),
                )
                ids[name] = existing
            else:
                ids[name] = self.client.mutate(
                    f"create {kind} “{name}”", lambda r=resource: create(r)
                )

        for name, resource_id in managed():
            if name not in defined:
                deletes.append(
                    lambda n=name, i=resource_id: self.client.mutate(
                        f"delete orphaned {kind} “{n}”", lambda: delete(i)
                    )
                )
        return ids

    @staticmethod
    def _by_name(items: Iterable[R], kind: str) -> dict[str, R]:
        """Index resources by name, refusing duplicates (they'd be ambiguous)."""
        result: dict[str, R] = {}
        for item in items:
            if item.name in result:
                raise NewRelicUpdaterError(f"Duplicate {kind} name '{item.name}' in definitions")
            result[item.name] = item
        return result

    def _reconcile_entities(
        self,
        kind: str,
        entity_type: str,
        items: list[R],
        create: Callable[[R], str],
        update: Callable[[str, R], None],
        delete: Callable[[str], None],
        deletes: list[Delete],
    ) -> dict[str, str | None]:
        """``_reconcile`` for resources owned via the managed tag.

        Resources are identified by entity GUID; ``create`` must return the new
        entity's GUID (and tag it, see ``_tag_managed``).
        """

        def find(name: str) -> str | None:
            entity = self._find_entity(name, entity_type)
            return entity["guid"] if entity else None

        def managed() -> list[tuple[str, str]]:
            return [(e["name"], e["guid"]) for e in self._managed_entities(entity_type)]

        return self._reconcile(
            kind=kind,
            defined=self._by_name(items, kind),
            find=find,
            managed=managed,
            create=create,
            update=update,
            delete=delete,
            deletes=deletes,
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

    def _tag_managed(self, guid: str) -> None:
        """Tag a freshly created entity so future runs recognize it as ours."""
        data = self.client.call(
            self._TAG,
            {
                "guid": guid,
                "tags": [{"key": self.managed_tag_key, "values": [self.managed_tag_value]}],
            },
        )
        if data["taggingAddTagsToEntity"]["errors"]:
            raise NewRelicUpdaterError(
                f"taggingAddTagsToEntity: {data['taggingAddTagsToEntity']['errors']}"
            )

    # -- Dashboards -----------------------------------------------------------

    def _sync_dashboards(self, dashboards: list[Dashboard], deletes: list[Delete]) -> None:
        self._reconcile_entities(
            kind="dashboard",
            entity_type="DASHBOARD",
            items=dashboards,
            create=self._create_dashboard,
            update=self._update_dashboard,
            delete=self._delete_dashboard,
            deletes=deletes,
        )

    def _dashboard_input(self, dashboard: Dashboard) -> dict:
        """Serialize a dashboard, injecting our account id into account-less queries."""
        payload = dashboard.as_nr_dict()
        for page in payload["pages"]:
            for widget in page["widgets"]:
                for nrql in widget["rawConfiguration"].get("nrqlQueries", []):
                    # A query that set neither accountId nor accountIds inherits
                    # the updater's account.
                    if not nrql.get("accountId") and not nrql.get("accountIds"):
                        nrql["accountId"] = self.account_id
        return payload

    # language=graphql
    _DASHBOARD_CREATE = """
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

    def _create_dashboard(self, dashboard: Dashboard) -> str:
        data = self.client.call(
            self._DASHBOARD_CREATE,
            {"accountId": self.account_id, "dashboard": self._dashboard_input(dashboard)},
        )
        result = data["dashboardCreate"]
        if result["errors"]:
            raise NewRelicUpdaterError(f"dashboardCreate: {result['errors']}")
        guid = result["entityResult"]["guid"]
        self._tag_managed(guid)
        return guid

    # language=graphql
    _DASHBOARD_UPDATE = """
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
            self._DASHBOARD_UPDATE, {"guid": guid, "dashboard": self._dashboard_input(dashboard)}
        )
        result = data["dashboardUpdate"]
        if result["errors"]:
            raise NewRelicUpdaterError(f"dashboardUpdate: {result['errors']}")

    # language=graphql
    _DASHBOARD_DELETE = """
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
        data = self.client.call(self._DASHBOARD_DELETE, {"guid": guid})
        result = data["dashboardDelete"]
        if result["errors"]:
            raise NewRelicUpdaterError(f"dashboardDelete: {result['errors']}")


def _collect(roots: Iterable[NrResource]) -> list[NrResource]:
    """``roots`` plus every resource reachable from them, each object once.

    Following references is what makes an inline resource and one held in a
    variable the same thing to ``sync()``.
    """
    found: dict[int, NrResource] = {}

    def visit(value: object) -> None:
        if isinstance(value, NrResource):
            if id(value) in found:
                return
            found[id(value)] = value
        if isinstance(value, NrModel):
            for _, field in value:
                visit(field)
        elif isinstance(value, list | tuple):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    for root in roots:
        visit(root)
    return list(found.values())


def _of_type(resources: list[NrResource], cls: type[T]) -> list[T]:
    return [r for r in resources if isinstance(r, cls)]
