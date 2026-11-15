# Contributing

Thanks for helping. The most useful contribution is data from a machine model that has not been
mapped yet: it tells everyone what the tools return for that model.

## Scope

lamarzocco-mcp is a thin MCP wrapper around [pylamarzocco](https://github.com/zweckj/pylamarzocco)'s
cloud client. Each tool calls one pylamarzocco method and returns La Marzocco's raw JSON, with
timestamps converted and a few private fields redacted. Please keep it that way:

- If pylamarzocco cannot do something, add it to pylamarzocco first, not here.
- No local storage, background processes, WebSocket or Bluetooth connections.
- Write tools are limited to the seven reversible settings in `write_tools.py`. Back flush,
  plumb-in, firmware updates and schedules are deliberately not exposed.

## Development setup

You need Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

CI runs the same four checks on every pull request. The tests use anonymized fixtures and need no
La Marzocco account.

To try the server end to end over stdio, as an MCP client starts it:

```bash
uv run python tests/smoke_stdio.py          # lists tools, no login needed
uv run python tests/smoke_stdio.py --live   # also fetches your latest shot
```

## Adding your machine model

This takes about ten minutes. Your machine must be on wifi and connected to La Marzocco's app,
and your account must use email and password (not Google or Apple sign-in).

1. **Store your login** in the system keyring. Nothing is written to the repo:

   ```bash
   uv run lamarzocco-mcp setup
   ```

2. **Record what the cloud API returns** for your machine. This only reads; it changes nothing:

   ```bash
   uv run python scripts/discover.py
   ```

   Raw responses go to `dumps/<timestamp>/`, which git ignores. They contain your serial
   number, machine name and wifi name. **Never commit them or paste them into an issue.**

3. **Anonymize the dump** into a fixture directory named after your model. Add `--redact` for
   anything else personal you spot, such as your own name:

   ```bash
   uv run python scripts/anonymize.py dumps/<timestamp> --out tests/fixtures/<model> --redact "Your Name"
   ```

   The script replaces serial numbers, machine names, emails, wifi names and tokens, and fails
   if any original value is still present. **Read the output yourself before committing it.**
   Shot timestamps are kept; shift or remove them if you prefer.

4. **Document the findings** in [docs/capabilities.md](docs/capabilities.md): add a column for
   your model to the summary table and a section with firmware versions and anything that
   behaves differently from the Linea Micra.

5. **Open a pull request** with the fixtures and the documentation change.

If you would rather not open a pull request, use the "New machine model" issue template and
describe what you found, without raw output.

## Pull requests

- Keep each pull request to one change.
- Add or update tests for behaviour changes.
- Never include credentials, raw dumps, serial numbers or other personal data, including in
  screenshots and logs.

## Releasing (maintainers)

Releases go to PyPI from GitHub Actions with
[trusted publishing](https://docs.pypi.org/trusted-publishers/), so no API token exists anywhere.

1. Bump `version` in `pyproject.toml` (or `uv version --bump patch`) and commit.
2. Tag and push: `git tag v0.1.1 && git push origin v0.1.1`.
3. `.github/workflows/release.yml` runs the checks, verifies the tag matches the version, builds,
   publishes to PyPI and creates a GitHub release.

One-time setup: on pypi.org, add a trusted publisher for project `lamarzocco-mcp` with owner
`EmilbMadsen`, repository `lamarzocco-mcp`, workflow `release.yml` and environment `pypi`.
