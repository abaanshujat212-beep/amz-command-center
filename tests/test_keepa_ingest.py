from services.ingest.pipelines.keepa import normalize_product


def test_normalize_product_converts_keepa_cents():
    row = normalize_product({"asin": "B001", "title": "Widget", "stats": {"buyBoxPrice": 1299, "salesRank": 12345}})
    assert row["asin"] == "B001"
    assert row["buy_box_price"] == 12.99
    assert row["sales_rank"] == 12345


def test_normalize_product_requires_asin():
    try:
        normalize_product({"title": "No asin"})
    except ValueError as exc:
        assert "missing asin" in str(exc)
    else:
        raise AssertionError("expected ValueError")
