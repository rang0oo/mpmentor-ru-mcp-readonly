"""The public entry point must not expose stock or price mutations."""

import asyncio

from readonly_mcp.server import READ_ONLY_TOOLS, build


def test_gateway_has_only_allowlisted_tools():
    gateway = build()
    names = set(gateway._tool_manager._tools)
    assert names == READ_ONLY_TOOLS
    assert len(names) == 45
    assert "wb_get_fbs_stocks" in names
    assert not any(
        part in name
        for name in names
        for part in ("write", "delete", "set_", "add_", "remove_", "use_cabinet")
    )


def test_gateway_exposes_catalog_without_credentials():
    gateway = build()
    result = asyncio.run(gateway.call_tool("wb_list_sections", {}))
    assert "total_endpoints" in result[0][0].text
