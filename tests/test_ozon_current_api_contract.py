from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _catalog(path: str) -> list[dict]:
    payload = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    return payload["endpoints"]


def _by_path(endpoints: list[dict]) -> dict[tuple[str, str], dict]:
    return {(entry["method"], entry["path"]): entry for entry in endpoints}


def test_seller_catalog_uses_current_order_and_review_versions():
    endpoints = _by_path(_catalog("ozon_mcp/endpoints.yaml"))

    current_read_methods = {
        ("POST", "/v4/posting/fbs/unfulfilled/list"),
        ("POST", "/v4/posting/fbs/list"),
        ("POST", "/v3/posting/fbo/list"),
        ("POST", "/v2/review/count"),
        ("POST", "/v2/review/info"),
        ("POST", "/v2/review/list"),
    }
    for method in current_read_methods:
        assert endpoints[method]["safety"] == "read"

    deprecated_versions = {
        ("POST", "/v3/posting/fbs/unfulfilled/list"),
        ("POST", "/v3/posting/fbs/list"),
        ("POST", "/v2/posting/fbo/list"),
        ("POST", "/v1/review/count"),
        ("POST", "/v1/review/info"),
        ("POST", "/v1/review/list"),
    }
    assert deprecated_versions.isdisjoint(endpoints)


def test_seller_catalog_exposes_current_read_only_inventory_and_finance_methods():
    endpoints = _by_path(_catalog("ozon_mcp/endpoints.yaml"))

    expected = {
        ("POST", "/v1/product/info/stocks-by-warehouse/fbo"),
        ("POST", "/v1/finance/accrual/by-day"),
        ("POST", "/v1/finance/accrual/postings"),
        ("POST", "/v1/finance/accrual/types"),
        ("POST", "/v1/analytics/local-sale/total"),
        ("POST", "/v1/analytics/local-sale/items-clusters/info"),
        ("POST", "/v1/analytics/local-sale/clusters-items/info"),
    }
    for method in expected:
        assert endpoints[method]["safety"] == "read"


def test_performance_catalog_exposes_current_product_statistics_as_read_only():
    endpoints = _by_path(_catalog("ozon_mcp/perf_endpoints.yaml"))

    assert endpoints[("POST", "/api/client/statistics/products/sku")]["safety"] == "read"


def test_performance_state_changing_get_methods_are_not_classified_as_read_only():
    endpoints = _by_path(_catalog("ozon_mcp/perf_endpoints.yaml"))

    mutating_gets = {
        ("GET", "/api/client/campaign/all_sku_promo/activate"),
        ("GET", "/api/client/campaign/all_sku_promo/deactivate"),
        ("GET", "/api/client/campaign/all_sku_promo/set_bid"),
    }
    for method in mutating_gets:
        assert endpoints[method]["safety"] == "write"

    deprecated = {
        ("POST", "/external/api/dynamic_budget"),
        ("POST", "/api/client/search_promo/bids/recommendation"),
        ("POST", "/api/client/campaign/search_promo/v2/bids/set"),
    }
    assert deprecated.isdisjoint(endpoints)


def test_typed_fbs_tool_uses_current_catalog_entry():
    endpoints = _catalog("ozon_mcp/endpoints.yaml")
    fbs = next(entry for entry in endpoints if entry["operation_id"] == "ozon_fbs_unfulfilled")

    assert fbs["path"] == "/v4/posting/fbs/unfulfilled/list"
    assert fbs["safety"] == "read"
