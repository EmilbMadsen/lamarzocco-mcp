# lamarzocco-mcp

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by La Marzocco.

An [MCP](https://modelcontextprotocol.io) server that lets Claude and other MCP clients read the
status, settings and shot data of La Marzocco home espresso machines, and optionally change a
few settings. It runs locally over stdio and is built on
[pylamarzocco](https://github.com/zweckj/pylamarzocco).

Ask things like "what was my last shot?", "is the machine on?" or, with write tools enabled,
"turn on the machine".

## Supported machines

Developed and tested on a Linea Micra. Other models supported by pylamarzocco should work; see
[docs/capabilities.md](https://github.com/EmilbMadsen/lamarzocco-mcp/blob/main/docs/capabilities.md)
for what has been verified per model.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 for you if needed)
- A La Marzocco account that uses a regular email/password login (not Google or Apple sign-in)
- The machine connected to wifi and set up in La Marzocco's app

## Setup

Store your La Marzocco login in the system keyring (macOS Keychain, Windows Credential Locker,
or the Secret Service on Linux). Nothing is written to disk:

```bash
uvx lamarzocco-mcp setup
```

It signs in, lists your machines and saves the one to use. Run it again to change account, or
`uvx lamarzocco-mcp setup --delete` to remove everything. On macOS, the first time the server reads
the keychain you may be asked to allow it; choose "Always Allow".

## Use with Claude

The server runs over stdio: your MCP client starts it when needed, so there is nothing to keep
running.

**Claude Code:**

```bash
claude mcp add --scope user lamarzocco -- uvx lamarzocco-mcp
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS),
then restart Claude Desktop:

```json
{
  "mcpServers": {
    "lamarzocco": {
      "command": "uvx",
      "args": ["lamarzocco-mcp"]
    }
  }
}
```

If Claude Desktop cannot find `uvx`, use its full path (`which uvx`, e.g.
`/opt/homebrew/bin/uvx`).

## Tools

Read-only by default. Each tool wraps one method of pylamarzocco's `LaMarzoccoCloudClient`.

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

Shot times (`extractionSeconds`) are pump time measured by the machine, usually a few seconds
shorter than a scale's timer.

### Optional write tools

Off by default. With `LAMARZOCCO_MCP_ALLOW_WRITE=1` in the server's environment, seven more tools
are registered:

| Tool | Changes |
|---|---|
| `set_power` | On (brewing mode) or standby |
| `set_steam` | Steam boiler on/off |
| `set_steam_target_level` | Steam level 1–3 (level-based machines such as the Linea Micra) |
| `set_coffee_target_temperature` | Coffee boiler target, °C |
| `set_pre_extraction_mode` | Pre-brewing on/off (or pre-infusion, where the machine has it) |
| `set_pre_extraction_times` | Pre-brewing seconds in and out |
| `set_smart_standby` | Automatic standby after N minutes |

Each request is checked against the limits the machine reports before it is sent, and the
setting is read back afterwards. Back flush, plumb-in, firmware updates and schedules are not
exposed.

To enable them in Claude Desktop, add an `env` block to the server entry:

```json
"lamarzocco": {
  "command": "uvx",
  "args": ["lamarzocco-mcp"],
  "env": { "LAMARZOCCO_MCP_ALLOW_WRITE": "1" }
}
```

In Claude Code: `claude mcp add --scope user -e LAMARZOCCO_MCP_ALLOW_WRITE=1 lamarzocco -- uvx lamarzocco-mcp`.

## Configuration

| Variable | Effect |
|---|---|
| `LAMARZOCCO_MCP_ALLOW_WRITE=1` | Registers the write tools |
| `LAMARZOCCO_SERIAL` | Use this machine instead of the one chosen in `setup` |

With several machines on the account, tools also take an optional `serial_number`.

## Security

- Your login and installation key are stored only in the system keyring.
- The server runs only locally over stdio; there is no network listener.
- Read-only unless you enable write tools.
- The server uses La Marzocco's undocumented cloud API through pylamarzocco, the same API their
  app uses. It can stop working if La Marzocco changes it.

## Contributing

Have a different La Marzocco model? Mapping what it returns takes about ten minutes; see
[CONTRIBUTING.md](https://github.com/EmilbMadsen/lamarzocco-mcp/blob/main/CONTRIBUTING.md).

## Credits

- [pylamarzocco](https://github.com/zweckj/pylamarzocco) by Josef Zweck (MIT)
- The [Home Assistant La Marzocco integration](https://www.home-assistant.io/integrations/lamarzocco/)

## License

MIT
