"""Read-only Codex gateway for WB, Ozon Seller, and Ozon Performance."""

from pathlib import Path

from mcp.types import ToolAnnotations
from mcp.server.fastmcp import FastMCP

from readonly_mcp.rnp import get_product_rnp
from readonly_mcp.analytics import (explain_marketplace_metrics, check_financial_summary,
                                    reconcile_marketplace_totals)
from readonly_mcp.finance import get_ozon_finance_audit

from core.transport import run as run_transport
from ozon_mcp.server import mcp as ozon_mcp
from ozon_perf_mcp.server import mcp as ozon_perf_mcp
from wb_mcp.server import mcp as wb_mcp


READ_ONLY_TOOLS = {
    "reconcile_marketplace_totals",
    "get_ozon_finance_audit",
    "explain_marketplace_metrics",
    "check_financial_summary",
    "get_product_rnp",
    "wb_check_auth",
    "wb_list_sections",
    "wb_get_section",
    "wb_search_methods",
    "wb_map",
    "wb_describe_method",
    "wb_call_method",
    "wb_get_raw",
    "wb_fetch_all",
    "wb_list_cabinets",
    "wb_list_workflows",
    "wb_get_workflow",
    "wb_get_sales",
    "wb_get_stocks",
    "wb_get_fbs_stocks",
    "wb_get_new_orders",
    "wb_get_prices",
    "ozon_check_auth",
    "ozon_list_sections",
    "ozon_get_section",
    "ozon_search_methods",
    "ozon_map",
    "ozon_describe_method",
    "ozon_call_method",
    "ozon_get_raw",
    "ozon_fetch_all",
    "ozon_list_cabinets",
    "ozon_list_workflows",
    "ozon_get_workflow",
    "ozon_get_products",
    "ozon_get_stocks",
    "ozon_get_prices",
    "ozon_get_fbs_unfulfilled",
    "ozon_perf_check_auth",
    "ozon_perf_list_sections",
    "ozon_perf_get_section",
    "ozon_perf_search_methods",
    "ozon_perf_map",
    "ozon_perf_describe_method",
    "ozon_perf_call_method",
    "ozon_perf_get_raw",
    "ozon_perf_fetch_all",
    "ozon_perf_list_cabinets",
    "ozon_perf_list_workflows",
    "ozon_perf_get_workflow",
}


def build() -> FastMCP:
    gateway = FastMCP(
        "marketplaces-mcp-ru-readonly",
        instructions=(
            "Read-only access to Wildberries, Ozon Seller, and Ozon Performance. "
            "No tool that writes, deletes, rotates credentials, or switches cabinets is exposed."
            " Before interpreting seller numbers use explain_marketplace_metrics for the exact "
            "market and operation_id. Never guess unknown fields. Confirm cabinet, period, "
            "date basis, currency, pagination completeness and source freshness. Distinguish "
            "ordered amounts, realized sales, accruals, payouts and profit. Unknown costs are "
            "not zero. Use check_financial_summary only with reconciled realized revenue and "
            "non-overlapping expenses; incomplete data must not produce a profit conclusion."
        ),
    )
    uri = "ui://marketplaces/product-rnp.html"
    gateway.tool(structured_output=True, meta={"ui": {"resourceUri": uri}},
                 annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                             openWorldHint=True))(get_product_rnp)
    for function in (explain_marketplace_metrics, check_financial_summary,
                     reconcile_marketplace_totals, get_ozon_finance_audit):
        gateway.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                        openWorldHint=function is get_ozon_finance_audit))(function)

    @gateway.resource(uri, mime_type="text/html;profile=mcp-app")
    def product_rnp_ui() -> str:
        return Path(__file__).with_name("rnp.html").read_text(encoding="utf-8")

    available = {
        **gateway._tool_manager._tools,
        **wb_mcp._tool_manager._tools,
        **ozon_mcp._tool_manager._tools,
        **ozon_perf_mcp._tool_manager._tools,
    }
    missing = READ_ONLY_TOOLS - available.keys()
    if missing:
        raise RuntimeError(f"Expected read-only tools are missing: {sorted(missing)}")
    gateway._tool_manager._tools.update(
        {name: available[name] for name in sorted(READ_ONLY_TOOLS)}
    )
    return gateway


def main() -> None:
    run_transport(build())


if __name__ == "__main__":
    main()
