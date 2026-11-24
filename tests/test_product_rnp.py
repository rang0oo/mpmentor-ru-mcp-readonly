import unittest
from datetime import date

from readonly_mcp.rnp import report


class ProductReport(unittest.IsolatedAsyncioTestCase):
    async def test_custom_day_range_compares_equal_length_period(self):
        async def ozon(query,body):
            self.assertEqual(body['date_from'],'2026-11-21')
            self.assertEqual(body['date_to'],'2026-11-22')
            return {'result':{'data':[]}}
        result=await report('ozon',None,100,date(2026,11,22),ozon=ozon,
                            start_date=date(2026,11,22))
        self.assertEqual(result['previous_start'],'2026-11-21')
        self.assertEqual(result['previous_end'],'2026-11-21')

    async def test_economics_totals_are_not_limited_to_visible_rows(self):
        from unittest.mock import patch, AsyncMock
        from decimal import Decimal
        async def ozon(query, body):
            return {'result': {'data': [] if body['offset'] else [
                {'dimensions': [{'id': str(i), 'name': str(i)}, {'id': '2026-11-16'}],
                 'metrics': [1, 100]} for i in range(2)]}}
        economics = ({'status': 'ok', 'rows': {}},
                     {'status': 'ok', 'rows': {'0': {'advertising_rub': Decimal(20)}},
                      'unallocated_advertising_rub': Decimal(0)})
        with patch('readonly_mcp.rnp_economics.fetch_economics', new=AsyncMock(return_value=economics)):
            result = await report('ozon', None, 1, date(2026, 11, 16), ozon=ozon,
                                  include_economics=True)
        market = result['markets']['Ozon']
        self.assertEqual(market['summary']['units'], 2)
        self.assertEqual(market['summary']['drr_in_orders'], 10)
        self.assertEqual(len(market['rows']), 1)
        self.assertTrue(market['display_truncated'])

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
