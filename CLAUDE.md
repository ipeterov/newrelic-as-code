# CLAUDE.md

Guidance for working on `newrelic-as-code` — a package for defining New Relic
dashboards (alerts later) as typed pydantic models and reconciling them to an
account.

## Layout

- `models/` — the model tree, split by concern; every model serializes via
  `as_nr_dict()` (camelCase + drop-None handled once in `base.py`).
  - `base.py` — `NrModel` (camelCase serializer) and `NrConfigModel` (adds the
    `raw` escape-hatch merge). Everything else stays declarative on top of these.
  - `query.py` — `NrqlQuery` (`accountId` singular | `accountIds` array).
  - `widget.py` — the envelope (`Layout`, `Link`), the generic `Widget` escape
    hatch, and one `*Widget` class per visualization (`LineWidget`, …), built by
    the `_widget()` factory: each pins its `visualization` and folds its config
    fields in flat, so viz and config can never disagree.
  - `variable.py` — `Variable` + the full ENUM/NRQL/STRING machinery.
  - `dashboard.py` — `Dashboard`, `Page`.
  - `config/common.py` — shared `rawConfiguration` option models (yAxis, legend,
    units, colors, thresholds×viz, …).
  - `config/widgets.py` — per-visualization config models the `*Widget` classes
    expose.
- `client.py` — `NerdGraphClient` (thin transport, retry + dry-run gate),
  endpoint constants, `NewRelicUpdaterError`.
- `updater.py` — `NewRelicUpdater`; `_reconcile` is resource-agnostic
  (find-by-managed-tag → create/update/delete-orphaned → refuse-unmanaged →
  dry-run) so alerts can reuse it.

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
