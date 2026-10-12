"""Regression tests for the current official Wildberries API contract."""

import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from wb_mcp import server


def test_wb_authorization_uses_bearer_scheme():
    assert server._build_headers({"token": "example-token"}) == {
        "Authorization": "Bearer example-token"
    }


def test_wb_authorization_does_not_duplicate_bearer_scheme():
    assert server._build_headers({"token": "Bearer example-token"}) == {
        "Authorization": "Bearer example-token"
    }


@pytest.mark.parametrize(
    "operation_id",
    ("wb_stats_stocks", "wb_report_realization", "wb_adv_fullstats"),
)
def test_disabled_wb_methods_are_not_in_catalog(operation_id):
    assert server.catalog.get(operation_id) is None


@pytest.mark.parametrize(
    "operation_id",
    (
        "wb_post_api_analytics_stocks_report_wb_warehouses",
        "wb_post_api_finance_sales_reports_detailed",
        "wb_get_adv_fullstats",
    ),
)
def test_replacements_for_disabled_wb_methods_are_in_catalog(operation_id):
    assert server.catalog.get(operation_id) is not None


def test_wb_stocks_rejects_chrt_ids_without_nm_ids():
    with pytest.raises(ToolError, match="nm_ids"):
        asyncio.run(server.mcp.call_tool(
            "wb_get_stocks", {"chrt_ids": [123], "limit": 100, "offset": 0}
        ))


@pytest.mark.parametrize(
    "arguments",
    (
        {"limit": 0},
        {"limit": 1001},
        {"offset": -1},
        {"filter_nm_id": 0},
    ),
)
def test_wb_prices_rejects_values_outside_official_limits(arguments):
    with pytest.raises(ToolError):
        asyncio.run(server.mcp.call_tool("wb_get_prices", arguments))
