"""Manual end-to-end check: start the server over stdio, like an MCP client does, and list tools.

    uv run python tests/smoke_stdio.py          # list tools only, no login needed
    uv run python tests/smoke_stdio.py --live   # also fetch your latest shot (uses the keyring)

Not part of the pytest suite: it spawns a subprocess, and --live talks to La Marzocco.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main(live: bool) -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "lamarzocco_mcp.server"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        print(f"connected to {init.server_info.name} v{init.server_info.version}")

        tools = (await session.list_tools()).tools
        print(f"\n{len(tools)} tools:")
        for tool in sorted(tools, key=lambda t: t.name):
            read_only = bool(tool.annotations and tool.annotations.read_only_hint)
            summary = (tool.description or "").strip().splitlines()[0]
            print(f"  [{'read ' if read_only else 'WRITE'}] {tool.name:30} {summary[:60]}")

        if live:
            result = await session.call_tool("get_last_coffees", {"limit": 1})
            if result.is_error:
                print(f"\nget_last_coffees -> error: {result.content}")
                return 1
            shot = (result.structured_content or {}).get("lastCoffees", [{}])[0]
            print("\nlatest shot:", json.dumps(shot, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--live" in sys.argv)))
