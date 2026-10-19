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

The order is dashboards, alert policies, NRQL conditions.

The reconcile core (``_reconcile``) is resource-agnostic: given how to find the
live resources of one kind, it upserts the defined ones and queues the orphaned
ones for deletion. What counts as "ours" comes in two forms:

- **Tagged** (dashboards, alert policies): an entity carrying our managed tag.
  ``_reconcile_entities`` finds them by entity search and refuses to clobber a
  same-named entity without the tag.
- **Belongs to something tagged** (NRQL conditions): every condition in one of
  our policies, matched by name within that policy.
"""

import base64
import warnings
from collections.abc import Callable, Iterable
from typing import Protocol, TypeVar

from .client import US_ENDPOINT, NerdGraphClient, NewRelicUpdaterError
from .models.alert import (
    AlertPolicy,
    AnyNrqlCondition,
    NrqlBaselineCondition,
    NrqlStaticCondition,
)
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
        policies = _of_type(defined, AlertPolicy)
        policy_ids = self._sync_alert_policies(policies, deletes)
        conditions = [
            r for r in defined if isinstance(r, NrqlStaticCondition | NrqlBaselineCondition)
        ]
        self._sync_conditions(policies, policy_ids, conditions, deletes)
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
        scope: str = "",
    ) -> dict[str, str | None]:
        """Reconcile one set of managed resources of a single kind.

        ``defined`` maps resource name -> the resource object to apply. For
        each, ``find(name)`` returns the id of the existing managed resource (or
        None, or raises if it must not be touched); we update it or create a new
        one. Every ``(name, id)`` from ``managed()`` that is no longer in
        ``defined`` is queued onto ``deletes`` as orphaned. ``scope`` is appended
        to log lines (e.g. which policy a condition belongs to).

        Returns name -> id for every defined resource: the existing id for
        updates, ``create``'s result for creates (None for a dry-run create).
        """
        ids: dict[str, str | None] = {}
        for name, resource in defined.items():
            existing = find(name)
            if existing:
                self.client.mutate(
                    f"update {kind} “{name}”{scope}",
                    lambda r=resource, i=existing: update(i, r),
                )
                ids[name] = existing
            else:
                ids[name] = self.client.mutate(
                    f"create {kind} “{name}”{scope}", lambda r=resource: create(r)
                )

        for name, resource_id in managed():
            if name not in defined:
                deletes.append(
                    lambda n=name, i=resource_id: self.client.mutate(
                        f"delete orphaned {kind} “{n}”{scope}", lambda: delete(i)
                    )
                )
        return ids

    @staticmethod
    def _by_name(items: Iterable[R], kind: str, scope: str = "") -> dict[str, R]:
        """Index resources by name, refusing duplicates (they'd be ambiguous)."""
        result: dict[str, R] = {}
        for item in items:
            if item.name in result:
                raise NewRelicUpdaterError(
                    f"Duplicate {kind} name '{item.name}'{scope} in definitions"
                )
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

    # -- Alert policies ---------------------------------------------------------
    #
    # Alerts mutations report failures as top-level GraphQL errors (no per-result
    # ``errors`` field), which ``NerdGraphClient.call`` already raises on. They
    # take a policy's numeric id rather than its entity GUID.

    def _sync_alert_policies(
        self, policies: list[AlertPolicy], deletes: list[Delete]
    ) -> dict[str, str | None]:
        """Reconcile policies; returns name -> policy id (None for a dry-run create).

        Deleting a policy deletes its conditions with it.
        """
        guids = self._reconcile_entities(
            kind="alert policy",
            entity_type="POLICY",
            items=policies,
            create=self._create_policy,
            update=self._update_policy,
            delete=self._delete_policy,
            deletes=deletes,
        )
        return {name: _guid_domain_id(guid) if guid else None for name, guid in guids.items()}

    # language=graphql
    _POLICY_CREATE = """
    mutation ($accountId: Int!, $policy: AlertsPolicyInput!) {
      alertsPolicyCreate(accountId: $accountId, policy: $policy) {
        id
        entityGuid
      }
    }
    """

    def _create_policy(self, policy: AlertPolicy) -> str:
        data = self.client.call(
            self._POLICY_CREATE, {"accountId": self.account_id, "policy": policy.as_nr_dict()}
        )
        guid = data["alertsPolicyCreate"]["entityGuid"]
        self._tag_managed(guid)
        return guid

    # language=graphql
    _POLICY_UPDATE = """
    mutation ($accountId: Int!, $id: ID!, $policy: AlertsPolicyUpdateInput!) {
      alertsPolicyUpdate(accountId: $accountId, id: $id, policy: $policy) {
        id
      }
    }
    """

    def _update_policy(self, guid: str, policy: AlertPolicy) -> None:
        self.client.call(
            self._POLICY_UPDATE,
            {
                "accountId": self.account_id,
                "id": _guid_domain_id(guid),
                "policy": policy.as_nr_dict(),
            },
        )

    # language=graphql
    _POLICY_DELETE = """
    mutation ($accountId: Int!, $id: ID!) {
      alertsPolicyDelete(accountId: $accountId, id: $id) {
        id
      }
    }
    """

    def _delete_policy(self, guid: str) -> None:
        self.client.call(
            self._POLICY_DELETE, {"accountId": self.account_id, "id": _guid_domain_id(guid)}
        )

    # -- NRQL conditions --------------------------------------------------------

    def _sync_conditions(
        self,
        policies: list[AlertPolicy],
        policy_ids: dict[str, str | None],
        conditions: list[AnyNrqlCondition],
        deletes: list[Delete],
    ) -> None:
        """Reconcile each managed policy's conditions to exactly the defined ones.

        A condition belongs to its policy: it's ours if its policy is ours, and
        it's matched by name within the policy (names are only unique per
        policy, so account-wide entity search can't find it). A condition in a
        managed policy that isn't defined is deleted.
        """
        for policy in policies:
            policy_id = policy_ids[policy.name]
            scope = f" in policy “{policy.name}”"
            defined = self._by_name(
                [c for c in conditions if c.policy is policy], "condition", scope
            )
            # (id, type) per live condition name. Nothing is live in a policy a
            # dry run would only create.
            live = self._policy_conditions(policy_id) if policy_id else {}

            # NerdGraph can't change a condition's type in place, so delete it
            # here and let the reconcile below create it with the new type.
            for name, condition in defined.items():
                if name in live and live[name][1] != condition.condition_type:
                    condition_id, live_type = live.pop(name)
                    self.client.mutate(
                        f"delete condition “{name}”{scope} to change its type "
                        f"{live_type} → {condition.condition_type}",
                        lambda i=condition_id: self._delete_condition(i),
                    )

            self._reconcile(
                kind="condition",
                defined=defined,
                find=lambda name, live=live: live[name][0] if name in live else None,
                managed=lambda live=live: [(name, i) for name, (i, _) in live.items()],
                create=lambda c, policy_id=policy_id: self._create_condition(policy_id, c),
                update=self._update_condition,
                delete=self._delete_condition,
                deletes=deletes,
                scope=scope,
            )

    # language=graphql
    _CONDITIONS_SEARCH = """
    query ($accountId: Int!, $policyId: ID!, $cursor: String) {
      actor {
        account(id: $accountId) {
          alerts {
            nrqlConditionsSearch(cursor: $cursor, searchCriteria: {policyId: $policyId}) {
              nextCursor
              nrqlConditions {
                id
                name
                type
              }
            }
          }
        }
      }
    }
    """

    def _policy_conditions(self, policy_id: str) -> dict[str, tuple[str, str]]:
        """name -> (id, type) of every NRQL condition in the policy."""
        conditions: dict[str, tuple[str, str]] = {}
        cursor = None
        while True:
            data = self.client.call(
                self._CONDITIONS_SEARCH,
                {"accountId": self.account_id, "policyId": policy_id, "cursor": cursor},
            )
            page = data["actor"]["account"]["alerts"]["nrqlConditionsSearch"]
            for c in page["nrqlConditions"]:
                if c["name"] in conditions:
                    raise NewRelicUpdaterError(
                        f"Multiple conditions named '{c['name']}' in policy {policy_id} — "
                        "refusing to guess. Resolve the duplicate in New Relic first."
                    )
                conditions[c["name"]] = (c["id"], c["type"])
            cursor = page["nextCursor"]
            if not cursor:
                return conditions

    # language=graphql
    _STATIC_CREATE = """
    mutation ($accountId: Int!, $policyId: ID!, $condition: AlertsNrqlConditionStaticInput!) {
      alertsNrqlConditionStaticCreate(
        accountId: $accountId, policyId: $policyId, condition: $condition
      ) {
        id
      }
    }
    """

    # language=graphql
    _BASELINE_CREATE = """
    mutation ($accountId: Int!, $policyId: ID!, $condition: AlertsNrqlConditionBaselineInput!) {
      alertsNrqlConditionBaselineCreate(
        accountId: $accountId, policyId: $policyId, condition: $condition
      ) {
        id
      }
    }
    """

    # language=graphql
    _STATIC_UPDATE = """
    mutation ($accountId: Int!, $id: ID!, $condition: AlertsNrqlConditionUpdateStaticInput!) {
      alertsNrqlConditionStaticUpdate(accountId: $accountId, id: $id, condition: $condition) {
        id
      }
    }
    """

    # language=graphql
    _BASELINE_UPDATE = """
    mutation ($accountId: Int!, $id: ID!, $condition: AlertsNrqlConditionUpdateBaselineInput!) {
      alertsNrqlConditionBaselineUpdate(accountId: $accountId, id: $id, condition: $condition) {
        id
      }
    }
    """

    _CONDITION_MUTATIONS = {
        # type -> (create mutation, its root field, update mutation)
        "STATIC": (_STATIC_CREATE, "alertsNrqlConditionStaticCreate", _STATIC_UPDATE),
        "BASELINE": (_BASELINE_CREATE, "alertsNrqlConditionBaselineCreate", _BASELINE_UPDATE),
    }

    def _create_condition(self, policy_id: str, condition: AnyNrqlCondition) -> str:
        mutation, field, _ = self._CONDITION_MUTATIONS[condition.condition_type]
        data = self.client.call(
            mutation,
            {
                "accountId": self.account_id,
                "policyId": policy_id,
                "condition": condition.as_nr_dict(),
            },
        )
        return data[field]["id"]

    def _update_condition(self, condition_id: str, condition: AnyNrqlCondition) -> None:
        _, _, mutation = self._CONDITION_MUTATIONS[condition.condition_type]
        self.client.call(
            mutation,
            {
                "accountId": self.account_id,
                "id": condition_id,
                # An update leaves omitted fields unchanged, so unset ones are
                # sent as nulls to reset them.
                "condition": condition.as_nr_dict(nulls=True),
            },
        )

    # language=graphql
    _CONDITION_DELETE = """
    mutation ($accountId: Int!, $id: ID!) {
      alertsConditionDelete(accountId: $accountId, id: $id) {
        id
      }
    }
    """

    def _delete_condition(self, condition_id: str) -> None:
        self.client.call(self._CONDITION_DELETE, {"accountId": self.account_id, "id": condition_id})


def _guid_domain_id(guid: str) -> str:
    """A resource's own id (e.g. a policy id) from its entity GUID.

    An entity GUID is unpadded base64 of ``accountId|domain|type|domainId``.
    """
    decoded = base64.b64decode(guid + "=" * (-len(guid) % 4)).decode()
    return decoded.split("|")[3]


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
