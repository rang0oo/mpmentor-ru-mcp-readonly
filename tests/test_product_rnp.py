import unittest
from datetime import date

from readonly_mcp.rnp import report


class ProductReport(unittest.IsolatedAsyncioTestCase):
    async def test_ozon_keeps_products_that_stopped_selling(self):
        async def ozon(query, body):
            def line(sku, day, qty, amount):
                return {"dimensions": [{"id": sku, "name": sku}, {"id": day}],
                        "metrics": [qty, amount]}
            return {"result": {"data": [] if body['offset'] else [
                line("old", "2026-11-09", 4, 200),
                line("grow", "2026-11-09", 2, 100),
                line("grow", "2026-11-16", 4, 200),
            ]}}

        result = await report("ozon", None, 8, date(2026, 11, 16), ozon=ozon)
        self.assertEqual([(row["sku"], row["change_pct"]) for row in result["markets"]["Ozon"]["rows"]],
                         [("grow", 100.0), ("old", -100.0)])

    async def test_wb_reports_source_error_without_hiding_ozon(self):
        async def wb(query, body):
            raise ValueError("bad payload")
        async def ozon(query, body):
            return {"result": {"data": []}}
        result = await report("all", None, 8, date(2026, 11, 16), wb, ozon)
        self.assertEqual(result["markets"]["WB"]["status"], "unavailable")
        self.assertEqual(result["markets"]["Ozon"]["rows"], [])

    async def test_server_capped_pages_are_not_lost(self):
        async def ozon(query, body):
            rows = [{"dimensions": [{"id": str(i), "name": str(i)},
                                    {"id": "2026-11-16"}], "metrics": [1, 100]}
                    for i in range(3)]
            offset = body['offset']
            return {"result": {"data": rows[offset:offset + 1]}}
        result = await report("ozon", None, 8, date(2026, 11, 16), ozon=ozon)
        self.assertEqual(result['markets']['Ozon']['total'], 3)
