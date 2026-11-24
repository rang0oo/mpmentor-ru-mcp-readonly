"""The public entry point must not expose stock or price mutations."""

import asyncio

from readonly_mcp.server import READ_ONLY_TOOLS, LOCAL_BUSINESS_TOOLS, build


def test_gateway_has_only_allowlisted_tools():
    gateway = build()
    names = set(gateway._tool_manager._tools)
    assert names == READ_ONLY_TOOLS | LOCAL_BUSINESS_TOOLS
    assert len(READ_ONLY_TOOLS) == 55
    assert len(names) == 58
    assert "wb_get_fbs_stocks" in names
    assert not any(
        part in name
        for name in READ_ONLY_TOOLS
        for part in ("write", "delete", "set_", "add_", "remove_", "use_cabinet")
    )


def test_gateway_exposes_catalog_without_credentials():
    gateway = build()
    result = asyncio.run(gateway.call_tool("wb_list_sections", {}))
    assert "total_endpoints" in result[0][0].text


def test_rnp_schema_advertises_display_limit_and_economics():
    gateway = build()
    tool = gateway._tool_manager._tools['get_product_rnp']
    fields = tool.parameters['properties']
    assert fields['limit']['maximum'] == 1000
    assert fields['limit']['minimum'] == 1
    assert fields['include_economics']['default'] is True
