# newrelic-as-code

Define New Relic dashboards as code and reconcile them to an account.

New Relic resources should be defined in version-controlled Python and
reconciled to the account on deploy, never hand-edited in the UI. You describe
dashboards as pydantic models and the library handles finding the resources it
manages, creating/updating/deleting them to match your declared set, and
refusing to clobber anything it didn't create.

Reconcile is safe by design:

- **Managed by tag.** The library only touches dashboards carrying its
  `managed-by` tag. A same-named dashboard without the tag is refused, never
  overwritten — so hand-built dashboards are safe.
- **Orphan cleanup.** A managed dashboard that's no longer in your declared set
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
    # The tag that marks dashboards this tool owns. Choose a value unique to your
    # deployment so several deployments can coexist in one account.
    managed_tag_value='my-service-deploy',
)
updater.sync([dashboard])
```

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
  widgets directly. Layout/composition helpers (grid math, managed banners)
  belong in your own code, since they're specific to how you lay dashboards out.
- **Extensible reconcile.** `sync()` reconciles dashboards today. The reconcile
  core (find-by-managed-tag → create/update/delete-orphaned → refuse-unmanaged →
  dry-run) is resource-agnostic, so alert policies/conditions can be added as
  additional resource types later without reshaping it.

## License

MIT

---

<sub>Not affiliated with or endorsed by New Relic, Inc. "New Relic" is a
trademark of New Relic, Inc.</sub>
