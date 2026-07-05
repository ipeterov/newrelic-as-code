# Development

This document is for maintainers of newrelic-as-code.

## Releasing a new version

Releases are automated via GitHub Actions. To publish a new version to PyPI:

1. Update the `version` in `pyproject.toml`
2. Commit and push to `main`

The CI workflow will:
- Run lint and the test suite (across Python 3.12–3.14)
- Check if the version in `pyproject.toml` is higher than what's on PyPI
- If yes, build and publish the new version

No manual PyPI uploads or tags required. The version in `pyproject.toml` is the
single source of truth.

### PyPI trusted publishing (OIDC)

Publishing uses PyPI trusted publishing (OIDC) — there is no long-lived PyPI
token stored anywhere. The `publish` job runs in the `pypi` GitHub environment
and mints a short-lived OIDC token that PyPI exchanges for upload rights.

**This is only safe because of configuration that lives outside `ci.yaml`.** A
pull request can propose arbitrary changes to `ci.yaml`, so the workflow file
itself can never be the thing that guards release credentials. Two settings do
that, and both must be in place:

1. **GitHub `pypi` environment → deployment branch rule = `main` only.**
   In *Settings → Environments → pypi*, restrict deployments to the `main`
   branch (protected-branch or selected-branch rule). GitHub then refuses to
   grant the environment's OIDC token to any job whose ref isn't `main`, so a
   PR (which runs on a `refs/pull/*` ref) cannot obtain it even if it edits the
   workflow to try. Optionally add required reviewers for a manual gate.

2. **PyPI trusted publisher pinned to this exact source.**
   On PyPI, the trusted publisher is configured with this repository, the
   workflow filename (`ci.yaml`), and the environment name (`pypi`). PyPI
   rejects any token whose subject doesn't match — so a token minted by a
   different workflow, or by a `publish` job that dropped `environment: pypi`,
   is not accepted.

In addition, `ci.yaml` gates publishing in depth: `check-version` only runs on a
push to `main` (`github.event_name == 'push' && github.ref == 'refs/heads/main'`),
and `publish` needs it, so the publish job never even starts on a pull request.
The two settings above are the parts that hold even if the YAML is modified.

## Local development

Install dependencies:

```bash
uv sync --group dev
```

Run linting:

```bash
uv run ruff check
uv run ruff format --check
```

Format code:

```bash
uv run ruff format
```
