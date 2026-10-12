"""The installed-style module starts and speaks MCP over stdio."""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_protocol_lists_only_read_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKETPLACE_MCP_HOME", str(tmp_path))
    for name in (
        "WB_API_TOKEN", "OZON_CLIENT_ID", "OZON_API_KEY",
        "OZON_PERF_CLIENT_ID", "OZON_PERF_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "readonly_mcp.server"],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert len(names) == 45
                assert "wb_get_fbs_stocks" in names
                assert "wb_write_method" not in names
                result = await session.call_tool("wb_list_sections", {})
                assert "total_endpoints" in result.content[0].text

    asyncio.run(run())
