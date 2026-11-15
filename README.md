# lamarzocco-mcp

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by La Marzocco.

An [MCP](https://modelcontextprotocol.io) server that lets Claude and other MCP clients read the
status, settings and shot data of La Marzocco home espresso machines. It runs locally over stdio
and is built on [pylamarzocco](https://github.com/zweckj/pylamarzocco).

**Status:** early work in progress. See [docs/capabilities.md](docs/capabilities.md) for what the API exposes.

## Supported machines

Developed and tested on a Linea Micra. Other models supported by pylamarzocco should work;
see [docs/capabilities.md](docs/capabilities.md) for what has been verified per model.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- A La Marzocco account that uses a regular email/password login (not Google or Apple sign-in)

## Setup (development)

```bash
uv sync
uv run python scripts/setup_credentials.py
```

Credentials and the installation key are stored in your system keyring. Only the machine's
serial number goes in `.env`.

## Use with Claude

The server runs over stdio: your MCP client starts it when needed, so there is nothing to keep
running. Replace the path with where you cloned the repo.

**Claude Code:**

```bash
claude mcp add --scope user lamarzocco -- uv --directory /path/to/lamarzocco-mcp run lamarzocco-mcp
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`), then
restart Claude Desktop:

```json
{
  "mcpServers": {
    "lamarzocco": {
      "command": "uv",
      "args": ["--directory", "/path/to/lamarzocco-mcp", "run", "lamarzocco-mcp"]
    }
  }
}
```

Then ask, for example, "what was my last shot?".

## Tools

All tools are read-only. Each wraps one method of pylamarzocco's `LaMarzoccoCloudClient`.

| Tool | Returns |
|---|---|
| `list_machines` | Machines on the account |
| `get_machine_status` | On/standby, boilers, pre-brewing, back flush |
| `get_machine_settings` | Firmware, wifi signal, plumb-in, auto-update |
| `get_statistics` | Statistics widgets from the app |
| `get_firmware_status` | Firmware update status |
| `get_schedule` | Smart standby and wake-up/sleep schedules |
| `get_coffee_and_flush_counter` | Total coffees and flushes |
| `get_last_coffees` | Latest 15 shots: time, extraction (pump) seconds, dose, temperature |
| `get_coffee_and_flush_trend` | Coffees and flushes per day, up to 30 days |

Responses are La Marzocco's raw JSON with three changes: timestamps become ISO 8601 in local time,
the Bluetooth token and wifi name are redacted, and image/tutorial URLs are dropped.

## Credits

- [pylamarzocco](https://github.com/zweckj/pylamarzocco) by Josef Zweck (MIT)
- The [Home Assistant La Marzocco integration](https://www.home-assistant.io/integrations/lamarzocco/)

## License

MIT
