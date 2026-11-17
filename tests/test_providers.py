import json
from pathlib import Path

import pytest

from price_radar.providers import ProviderError, detect_source
from price_radar.providers.ozon import ozon_sku, parse_price, parse_product
from price_radar.providers.wb import nm_id, parse_card

FIX = Path(__file__).parent / "fixtures"


def test_detect_source():
    assert detect_source("https://www.wildberries.ru/catalog/233123425/detail.aspx") == "wb"
    assert detect_source("https://www.ozon.ru/product/filtr-maslyanyy-mann-1234567/") == "ozon"
    with pytest.raises(ProviderError):
        detect_source("https://example.com/item/1")


def test_wb_ids_and_card():
    url = "https://www.wildberries.ru/catalog/233123425/detail.aspx"
    assert nm_id(url) == 233123425
    offer = parse_card(json.loads((FIX / "wb_card.json").read_text()), url)
    assert offer.price == 874.0  # cheapest size, kopecks -> roubles
    assert offer.in_stock is True
    assert offer.seller == "АвтоДеталь+"


def test_wb_empty_card():
    with pytest.raises(ProviderError):
        parse_card({"products": []}, "u")


def test_ozon_sku_and_price():
    assert ozon_sku("https://www.ozon.ru/product/filtr-maslyanyy-mann-w-712-95-1234567/?at=x") == "1234567"
    assert ozon_sku("https://ozon.ru/product/987654321") == "987654321"
    assert parse_price("1 990 ₽") == 1990.0
    assert parse_price("1 990,50 ₽") == 1990.5
    assert parse_price(None) is None


def test_ozon_product_mapping():
    card = json.loads((FIX / "ozon_product.json").read_text())
    offer = parse_product(card, "https://www.ozon.ru/product/x-1234567/")
    assert offer.price == 869.0
    assert offer.seller == "ZapMarket"
    assert offer.in_stock is True
    card["price"] = {"price": None}
    with pytest.raises(ProviderError):
        parse_product(card, "u")
