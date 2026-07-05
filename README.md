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

```python
from newrelic_as_code import (
    Dashboard,
    NewRelicUpdater,
    NrqlQuery,
    Page,
    Widget,
    EU_ENDPOINT,
)

dashboard = Dashboard(
    name='My service',
    pages=[
        Page(
            name='Overview',
            widgets=[
                Widget(
                    title='Throughput',
                    visualization='viz.line',
                    column=1,
                    row=1,
                    queries=[
                        NrqlQuery(
                            query='SELECT rate(count(*), 1 minute) '
                            'FROM Transaction TIMESERIES',
                        ),
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

- **Account id.** `account_id` is the account dashboards are created in, and is
  injected into any `NrqlQuery` that doesn't set its own `account_ids`. Set
  `account_ids` on a query explicitly to query across (or a different) account.
- **`raw_configuration`.** `Widget.raw_configuration` is merged into New Relic's
  `rawConfiguration` verbatim, so any chart option (units, colors, markers,
  thresholds, yAxis, gauge settings, …) is available without the library
  modelling it.
- **Variables.** Dashboard-level template variables are supported via the
  `Variable` model and `Dashboard(variables=[...])`.
- **No builder.** The library's surface is the plain
  `Dashboard`/`Page`/`Widget`/`NrqlQuery`/`Variable` model tree — you construct
  those directly. Any layout/composition helpers (grid math, managed banners)
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
