# newrelic-as-code

Define New Relic dashboards and alerts as code and reconcile them to an account.

New Relic resources should be defined in version-controlled Python and
reconciled to the account on deploy, never hand-edited in the UI. You describe
them as pydantic models and the library makes the account match: it finds the
resources it manages, creates/updates/deletes them to match your declared set,
and refuses to clobber anything it didn't create.

Each model is one New Relic resource, with NerdGraph's own field names and its
own required/optional fields — so New Relic's documentation for a resource is
the documentation for its model. There's no layer that generates resources for
you; helpers that cut down repetition belong in your own code.

Reconcile is safe by design:

- **Managed by tag.** The library only touches dashboards and alert policies
  carrying its `managed-by` tag. A same-named one without the tag is refused,
  never overwritten — so hand-built resources are safe.
- **Orphan cleanup.** A managed resource that's no longer in your declared set
  is deleted.
- **Dry run.** Pass `dry_run=True` to print what would change without touching
  the account.

## Installation

```bash
pip install newrelic-as-code
```

## Usage

There's one widget class per visualization — `LineWidget`, `BillboardWidget`,
`TableWidget`, … — each exposing exactly the config that visualization supports.
You pick the widget, not a visualization string, so a config can never disagree
with its chart type.

```python
from newrelic_as_code import (
    BillboardThreshold,
    BillboardWidget,
    Dashboard,
    EU_ENDPOINT,
    Layout,
    Legend,
    LineWidget,
    NewRelicUpdater,
    NrqlQuery,
    Page,
    YAxisLeft,
)

dashboard = Dashboard(
    name='My service',
    pages=[
        Page(
            name='Overview',
            widgets=[
                LineWidget(
                    title='Throughput',
                    layout=Layout(column=1, row=1),
                    nrql_queries=[
                        NrqlQuery(
                            query='SELECT rate(count(*), 1 minute) '
                            'FROM Transaction TIMESERIES',
                        ),
                    ],
                    legend=Legend(enabled=True),
                    y_axis_left=YAxisLeft(zero=True),
                ),
                BillboardWidget(
                    title='Error count',
                    layout=Layout(column=5, row=1),
                    nrql_queries=[
                        NrqlQuery(query='SELECT count(*) FROM TransactionError'),
                    ],
                    thresholds=[
                        BillboardThreshold(alert_severity='critical', value=100),
                    ],
                ),
            ],
        ),
    ],
)

updater = NewRelicUpdater(
    account_id=1234567,
    api_key='NRAK-...',
    # Defaults to the US region; pass EU_ENDPOINT (or any full URL) for others.
    endpoint=EU_ENDPOINT,
    # The tag that marks resources this tool owns. Choose a value unique to your
    # deployment so several deployments can coexist in one account.
    managed_tag_value='my-service-deploy',
)
updater.sync([dashboard])
```

### Alerts

An `AlertPolicy` groups conditions; each condition points at its policy, as in
New Relic. `NrqlStaticCondition` alerts on a fixed threshold,
`NrqlBaselineCondition` on deviation from a learned baseline.

```python
from newrelic_as_code import (
    AlertPolicy,
    ConditionNrql,
    NrqlStaticCondition,
    Signal,
    StaticTerm,
)

policy = AlertPolicy(name='My service', incident_preference='PER_CONDITION')

errors = NrqlStaticCondition(
    policy=policy,
    name='Error count',
    enabled=True,
    nrql=ConditionNrql(query='SELECT count(*) FROM TransactionError'),
    signal=Signal(aggregation_window=60),
    terms=[
        StaticTerm(
            operator='ABOVE',
            priority='CRITICAL',
            threshold=100,
            threshold_duration=300,
            threshold_occurrences='ALL',
        ),
    ],
)

updater.sync([dashboard, errors])
```

### What `sync()` does

The list you pass is the complete desired state. `sync()` manages every
resource in it plus every resource those reference — above, `policy` is managed
because `errors` points at it — so a resource can be written inline or held in
a variable. Then, in two passes over the resource kinds in dependency order
(dashboards, alert policies, NRQL conditions):

1. every defined resource is created, or updated if it already exists;
2. every managed resource that isn't defined is deleted, in reverse order.

Resources are matched to live ones by name. Dashboards and alert policies are
ours if they carry the managed tag; a condition is ours if its policy is.

## Notes

- **One widget per visualization.** `LineWidget`, `AreaWidget`, `BarWidget`,
  `StackedBarWidget`, `PieWidget`, `BillboardWidget`, `TableWidget`,
  `HeatmapWidget`, `HistogramWidget`, `JsonWidget`, `FunnelWidget`,
  `BulletWidget`, `MarkdownWidget`. Each carries its own config fields directly
  (no separate config object to keep in sync with a visualization string).
- **Account id.** `account_id` is the account dashboards are created in, and is
  injected into any `NrqlQuery` that sets neither `account_id` nor `account_ids`.
  Set `account_id` (single) or `account_ids` (multi-account) on a query to
  override.
- **Escape hatch.** New Relic's per-widget `rawConfiguration` is an untyped
  scalar, so the typed fields cover the keys we model — anything else goes
  through `raw={...}` on any widget, which is merged over (and wins against) the
  typed output. For an entirely unmodeled visualization, the generic `Widget`
  takes a `visualization` string and a full `raw_configuration` dict.
- **Variables.** Dashboard-level template variables (ENUM, NRQL, and STRING) are
  supported via the `Variable` model and `Dashboard(variables=[...])`.
- **No builder.** The library's surface is the plain model tree — you construct
  widgets and conditions directly. Composition helpers (grid math, a function
  that stamps out one condition per service) belong in your own code, since
  they're specific to your setup.
- **Conditions belong to their policy.** A managed policy's conditions are made
  to match exactly the conditions pointing at it, so a condition hand-added to
  a managed policy is deleted on the next sync. Condition names must be unique
  within a policy.
- **Condition type changes recreate.** New Relic can't change a condition
  between static and baseline in place, so the old one is deleted and a new one
  created (with a new id; its open incidents close).
- **Not modeled yet:** notifications (workflows, channels, destinations), other
  condition types (compound, and the legacy APM/infrastructure/synthetics
  conditions), and muting rules. Outlier conditions (removed by New Relic) and
  fields New Relic marks deprecated are left out on purpose.
- **`sync(dashboards=...)`** from 0.2 still works, with a `DeprecationWarning`;
  pass the list positionally instead.

## License

MIT

---

<sub>Not affiliated with or endorsed by New Relic, Inc. "New Relic" is a
trademark of New Relic, Inc.</sub>
