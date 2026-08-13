from beanly.main import app


def test_stage24_openapi_exposes_promotion_and_order_discount_contracts() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/promotions": {"get", "post"},
        "/api/v1/promotions/{promotion_id}": {"get", "patch"},
        "/api/v1/promotions/{promotion_id}/activate": {"post"},
        "/api/v1/promotions/{promotion_id}/archive": {"post"},
        "/api/v1/promotions/{promotion_id}/preview": {"post"},
        "/api/v1/promotions/{promotion_id}/codes": {"post"},
        "/api/v1/promotions/{promotion_id}/codes/{code_id}": {"delete"},
        "/api/v1/sales/orders/{order_id}/discounts/manual": {"post"},
        "/api/v1/sales/orders/{order_id}/discounts/code": {"post"},
        "/api/v1/sales/orders/{order_id}/discounts/custom": {"post"},
        "/api/v1/sales/orders/{order_id}/discounts/{discount_id}": {"delete"},
    }
    for path, methods in expected.items():
        assert path in paths, path
        assert methods <= set(paths[path]), (path, methods - set(paths[path]))
