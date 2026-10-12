"""Regression tests for current WB-owned warehouse stock reads."""

import asyncio
import json

from core.workflows import Workflows
from wb_mcp import server


def test_wb_get_stocks_uses_current_analytics_endpoint(monkeypatch):
    captured = {}

    async def fake_call_spec(spec, path_values=None, query=None, json_body=None):
        captured.update(spec=spec, query=query, body=json_body)
        return {"ok": True, "status": 200, "data": {"items": []}}

    monkeypatch.setattr(server.client, "call_spec", fake_call_spec)
    result = asyncio.run(server.mcp.call_tool(
        "wb_get_stocks", {"limit": 100, "offset": 0, "nm_ids": [123]},
    ))
    payload = json.loads(result[0][0].text)
    assert payload["ok"] is True
    assert captured["spec"].operation_id == "wb_post_api_analytics_stocks_report_wb_warehouses"
    assert captured["query"] is None
    assert captured["body"] == {"limit": 100, "offset": 0, "nmIds": [123]}


def test_stock_workflows_do_not_use_retired_endpoint():
    workflows = Workflows.from_yaml(server.WORKFLOWS_PATH)
    for name in ("stock_health", "reorder_planner"):
        operation_ids = {step["operation_id"] for step in workflows.get(name)["steps"]}
        assert "wb_stats_stocks" not in operation_ids
        assert "wb_post_api_analytics_stocks_report_wb_warehouses" in operation_ids
