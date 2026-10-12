"""Seller FBS stock reads remain distinct from WB-owned stock."""

import asyncio
import json

from core.safety import infer_safety
from wb_mcp import server


def test_fbs_stock_read_is_not_a_write():
    read = server.catalog.get("wb_post_api_stocks_warehouseid")
    update = server.catalog.get("wb_fbs_stock_update")
    delete = server.catalog.get("wb_delete_api_stocks_warehouseid")
    assert infer_safety(read.method, read.safety) == "read"
    assert infer_safety(update.method, update.safety) == "write"
    assert infer_safety(delete.method, delete.safety) == "destructive"


def test_fbs_stock_tool_uses_seller_warehouse_endpoint(monkeypatch):
    captured = {}

    async def fake_call_spec(spec, path_values=None, query=None, json_body=None):
        captured.update(spec=spec, path_values=path_values, body=json_body)
        return {"ok": True, "status": 200,
                "data": {"stocks": [{"chrtId": 123, "amount": 10}]}}

    monkeypatch.setattr(server.client, "call_spec", fake_call_spec)
    result = asyncio.run(server.mcp.call_tool(
        "wb_get_fbs_stocks", {"warehouse_id": 42, "chrt_ids": [123]},
    ))
    payload = json.loads(result[0][0].text)
    assert payload["data"]["stocks"][0]["amount"] == 10
    assert captured["spec"].operation_id == "wb_post_api_stocks_warehouseid"
    assert captured["path_values"] == {"warehouseId": 42}
    assert captured["body"] == {"chrtIds": [123]}
