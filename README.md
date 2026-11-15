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

## Credits

- [pylamarzocco](https://github.com/zweckj/pylamarzocco) by Josef Zweck (MIT)
- The [Home Assistant La Marzocco integration](https://www.home-assistant.io/integrations/lamarzocco/)

## License

MIT
