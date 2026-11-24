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
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                names = set(tools)
                assert len(names) == 58
                assert tools['save_business_settings'].annotations.readOnlyHint is False
                assert tools['save_business_settings'].annotations.openWorldHint is False
                report = tools["get_product_rnp"]
                assert report.annotations.readOnlyHint
                uri = report.meta["ui"]["resourceUri"]
                resource = (await session.read_resource(uri)).contents[0]
                assert resource.mimeType == "text/html;profile=mcp-app"
                assert "ui/notifications/tool-result" in resource.text
                rnp = await session.call_tool("get_product_rnp", {"market": "wb", "end_date": "2026-10-31"})
                assert rnp.structuredContent["markets"]["WB"]["status"] == "unavailable"
                assert "wb_get_fbs_stocks" in names
                assert "wb_write_method" not in names
                result = await session.call_tool("wb_list_sections", {})
                assert "total_endpoints" in result.content[0].text

    asyncio.run(run())
