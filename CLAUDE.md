# CLAUDE.md

Guidance for working on `newrelic-as-code` — a package for defining New Relic
dashboards and alerts as typed pydantic models and reconciling them to an
account.

## Design rule (the "vibe")

The package should feel like CDK: explicit, easy to review (if tedious), and a
direct map of New Relic's own entities, so **New Relic's documentation and
concepts double as ours**. Concretely:

- **One model per NerdGraph resource**, with NerdGraph's field names. A
  resource (anything with its own create/update/delete mutations) is an
  `NrResource`; parts of one resource's input (pages, widgets, terms, signal)
  are nested plain models.
- **NerdGraph's required/optional split.** A field NerdGraph requires has no
  default; an optional one defaults to None (New Relic's own default). No
  invented defaults, no derived or generated fields.
- **References point the way New Relic's do**, and hold the object itself
  (a condition has `policy=`, because NerdGraph's condition has `policyId`).
  `sync()` follows references, so inline vs. a variable is the user's choice.
- **The rollout stays trivial to explain:** create/update every kind in
  dependency order, then delete orphans in reverse order. A new resource kind
  slots into that order; it doesn't add a new mechanism.
- **Convenience lives in the consumer's code** (helpers that stamp out
  conditions, widget grids), never as a generating layer in this package.

Downstream users pin PyPI versions, so `main` may move ahead of the last
release, but released public API changes need a deprecation path, not a break.
Development is trunk-based: small, separately reviewable commits straight to
`main`.

## Layout

- `models/` — the model tree, split by concern; every model serializes via
  `as_nr_dict()` (camelCase + drop-None handled once in `base.py`).
  - `base.py` — `NrModel` (camelCase serializer; `nulls=True` renders unset
    fields as explicit nulls for update mutations), `NrResource` (marks a
    top-level resource) and `NrConfigModel` (adds the `raw` escape-hatch
    merge). Everything else stays declarative on top of these.
  - `query.py` — `NrqlQuery` (`accountId` singular | `accountIds` array).
  - `widget.py` — the envelope (`Layout`, `Link`), the generic `Widget` escape
    hatch, and one `*Widget` class per visualization (`LineWidget`, …), built by
    the `_widget()` factory: each pins its `visualization` and folds its config
    fields in flat, so viz and config can never disagree.
  - `variable.py` — `Variable` + the full ENUM/NRQL/STRING machinery.
  - `dashboard.py` — `Dashboard`, `Page`.
  - `alert.py` — `AlertPolicy` and the NRQL conditions (`NrqlStaticCondition`,
    `NrqlBaselineCondition`, their terms/signal/expiration), mirroring the
    `AlertsPolicyInput` / `AlertsNrqlCondition*Input` GraphQL types. Each
    condition class pins its `condition_type` ClassVar, which picks the
    create/update mutation; `policy` is the mutation's `policyId` argument and
    is left out of the input.
  - `config/common.py` — shared `rawConfiguration` option models (yAxis, legend,
    units, colors, thresholds×viz, …).
  - `config/widgets.py` — per-visualization config models the `*Widget` classes
    expose.
- `client.py` — `NerdGraphClient` (thin transport, retry + dry-run gate),
  endpoint constants, `NewRelicUpdaterError`.
- `updater.py` — `NewRelicUpdater`. `sync(resources)` collects the passed
  resources plus everything they reference (`_collect`), runs one `_sync_*`
  step per kind in dependency order (dashboards → alert policies → NRQL
  conditions), then runs the queued orphan deletions in reverse.
  `_reconcile` is resource-agnostic (takes `find`/`managed` callables,
  upserts, queues orphan deletes, returns name → id). Two ownership forms sit
  on top:
  - tagged entities (dashboards, alert policies) via `_reconcile_entities`:
    entity search + managed tag, refuse-unmanaged;
  - things that belong to a tagged entity (NRQL conditions → their policy):
    listed via `nrqlConditionsSearch(policyId)`, since condition names are only
    unique per policy.
  Alerts mutations take the numeric policy id, decoded from the entity GUID
  (`_guid_domain_id`).

**Public API:** the root `__init__.py` is the single curated public surface —
it imports directly from the leaf modules and lists everything in `__all__`
(grouped by concern, not sorted). The intermediate `models/__init__.py` and
`config/__init__.py` deliberately re-export nothing. To expose a new name:
define it in its leaf module, then add it to the root `__init__` import + `__all__`
— that one file is the source of truth for what's public.

## Where the dashboard JSON shape comes from (the reference for the models)

The dashboard JSON has **two tiers** with different sources of truth. This
matters because expanding the models means porting each tier from its reference,
not guessing.

(Alerts are simpler: policies and NRQL conditions are fully typed in the
GraphQL schema — mirror the `Alerts*Input` types the same way as tier 1 below.)

### Tier 1 — the envelope (typed, authoritative)

Pages, widgets' outer fields, variables, permissions are fully typed in the
NerdGraph **GraphQL schema** as `Dashboard*Input` types (`DashboardInput`,
`DashboardPageInput`, `DashboardWidgetInput`, `DashboardWidgetLayoutInput`,
`DashboardVariableInput` and its sub-inputs, etc.). This is machine-readable and
authoritative — mirror these types 1:1.

The schema is introspected into `nerdgraph.schema.graphql` (gitignored, large,
regenerated locally — see `graphql.config.yaml` for the `npx get-graphql-schema`
command). It also drives the `# language=graphql` injections in the source.

### Tier 2 — `rawConfiguration` (per-widget chart config)

In GraphQL this is `scalar DashboardWidgetRawConfiguration` — opaque at the API
boundary. **But New Relic validates its shape server-side**, so there is a real,
knowable schema. It is *not* published as GraphQL/JSON Schema/LLM-docs (NR's docs
are prose-only and don't fully enumerate the keys).

**The de-facto schema is published as code** in New Relic's open-source Terraform
provider: `newrelic/terraform-provider-newrelic`, file
`newrelic/structures_newrelic_one_dashboard.go` — its `expand*`/`flatten*`
functions build the real camelCase `rawConfiguration` JSON. That file is the
reference for widget config keys. (NR's Dashboard Services team recommends using
`rawConfiguration` over the typed `configuration` path, so raw-config-only is the
recommended direction, not a shortcut.)

Real `rawConfiguration` keys (per that provider):

- `nrqlQueries`: `[{accountId | accountIds, query}]` — NerdGraph accepts **both**
  `accountId` (singular) and `accountIds` (array, multi-account). Not a bug.
- `yAxisLeft` `{zero, min, max}`; `yAxisRight` `{zero, min, max, series:[{name}]}`
- `legend` `{enabled}`; `facet` `{showOtherSeries}`; `tooltip` `{mode}`
- `units` `{unit, seriesOverrides:[{unit, seriesName}]}`
- `colors` `{color, seriesOverrides:[{color, seriesName}]}`
- `nullValues` `{nullValue, seriesOverrides:[{nullValue, seriesName}]}`
- thresholds differ by viz — line: `{isLabelVisible, thresholds:[{from,to,name,severity}]}`;
  billboard: `[{alertSeverity, value}]`; table: `[{from,to,columnName,severity}]`
- `dataFormat`: `[{type,name,format,precision}]`; `initialSorting` `{direction,name}`
- `linkedEntityGuids`: `[str]`; `refreshRate` `{frequency}`;
  `platformOptions` `{ignoreTimeRange}`; markdown `text`

### Keeping the models in sync (intended mechanism — not all built yet)

- **Envelope:** the plan is a drift test that parses `nerdgraph.schema.graphql`
  and asserts our models cover each `Dashboard*Input` field (skipping if the
  schema file is absent). Not implemented yet — for now, re-check by hand against
  the schema when NR changes.
- **rawConfiguration:** ported from the provider Go file; re-fetch it (gitignored
  local copy) and diff when NR updates. Spot-validate by reading real dashboards
  back (`DashboardWidget.rawConfiguration` is returned non-null on the read side).
- **Escape hatch:** every widget config keeps a `raw_configuration` dict that
  merges over the typed fields — so an unmodeled-but-valid key is always
  expressable and the type system is never *wrong*.

## Conventions

- `pyproject.toml` `version` is the single source of truth; `__version__` reads it
  via `importlib.metadata`. Don't hardcode a second copy.
- Publishing is via trusted publishing (OIDC) on the `pypi` GitHub environment
  restricted to `main` — see `DEVELOPMENT.md`.
