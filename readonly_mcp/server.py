"""Read-only Codex gateway for WB, Ozon Seller, and Ozon Performance."""

from pathlib import Path

from mcp.types import ToolAnnotations
from mcp.server.fastmcp import FastMCP

from readonly_mcp.rnp import get_product_rnp
from readonly_mcp.analytics import (explain_marketplace_metrics, check_financial_summary,
                                    reconcile_marketplace_totals)
from readonly_mcp.finance import get_ozon_finance_audit
from readonly_mcp.business_settings import get_business_settings, save_business_settings
from readonly_mcp.ozon_advertising import get_ozon_advertising_details
from readonly_mcp.business_reports import business_report
from readonly_mcp.methodology import (allocate_expense,calculate_pnl,forecast_sales,
                                      explain_business_methodology)

from core.transport import run as run_transport
from ozon_mcp.server import mcp as ozon_mcp
from ozon_perf_mcp.server import mcp as ozon_perf_mcp
from wb_mcp.server import mcp as wb_mcp


READ_ONLY_TOOLS = {
    "reconcile_marketplace_totals",
    "get_ozon_finance_audit",
    "get_ozon_advertising_details",
    "explain_marketplace_metrics",
    "check_financial_summary",
    "get_product_rnp",
    "allocate_business_expense",
    "calculate_business_pnl",
    "forecast_business_sales",
    "explain_business_methodology",
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
LOCAL_BUSINESS_TOOLS = {'get_business_settings','save_business_settings','business_report'}


def build() -> FastMCP:
    gateway = FastMCP(
        "marketplaces-mcp-ru-readonly",
        instructions=(
            "Read-only access to Wildberries, Ozon Seller, and Ozon Performance. "
            "No tool that mutates marketplaces, rotates credentials, or switches cabinets is exposed."
            " save_business_settings writes only user-confirmed costs and tax settings to a local database."
            " Before profit calculations call get_business_settings; ask its questions in chat and save the answers."
            " Never assume missing costs, tax rates, VAT, or effective dates."
            " Before independent calculations read explain_business_methodology. Distinguish gross-sales,"
            " net-sales, orders and forecast DRR bases. Keep shared expenses at business level unless"
            " an allocation method is explicitly selected. Do not claim our models reproduce unverified MPSTATS rules."
            " Data collection is on demand only: no background refresh, scheduler, or automatic backfill."
            " business_report refresh fetches and saves only the requested period; saved/export use local data only."
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
                     reconcile_marketplace_totals, get_ozon_finance_audit,get_ozon_advertising_details):
        gateway.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                        openWorldHint=function in (get_ozon_finance_audit,get_ozon_advertising_details)))(function)
    gateway.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,
                 openWorldHint=False))(get_business_settings)
    gateway.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,
                 openWorldHint=False))(save_business_settings)
    gateway.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,
                 openWorldHint=True))(business_report)
    for name,function in (('allocate_business_expense',allocate_expense),
                          ('calculate_business_pnl',calculate_pnl),
                          ('forecast_business_sales',forecast_sales),
                          ('explain_business_methodology',explain_business_methodology)):
        gateway.tool(name=name,annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,
                     openWorldHint=False))(function)

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
