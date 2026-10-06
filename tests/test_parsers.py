import json
from pathlib import Path

from smartwebsearch.sources.mercadolibre import parse_api_results, parse_listing_html
from smartwebsearch.sources.vtex import parse_products

FIXTURES = Path(__file__).parent / "fixtures"


def test_mercadolibre_listing_html():
    offers = parse_listing_html((FIXTURES / "mercadolibre_listing.html").read_text())
    assert len(offers) == 2
    a55, moto = offers
    assert a55.title == "Samsung Galaxy A55 5G 256 GB Azul"
    assert a55.price == 649999.50
    assert a55.original_price == 799999
    assert a55.url == "https://www.mercadolibre.com.ar/samsung-galaxy-a55/p/MLA123"
    assert a55.free_shipping is True
    assert "6 cuotas" in a55.installments
    assert moto.price == 429000
    assert moto.original_price is None


def test_mercadolibre_api():
    data = json.loads((FIXTURES / "mercadolibre_api.json").read_text())
    [offer] = parse_api_results(data["results"])
    assert offer.price == 1299999
    assert offer.seller == "TIENDA_OFICIAL"
    assert offer.installments == "12x $108333.25 sin interés"


def test_vtex_products_skips_out_of_stock():
    products = json.loads((FIXTURES / "vtex_search.json").read_text())
    [offer] = parse_products(products, "oncity")
    assert offer.source == "oncity"
    assert offer.price == 499999.0
    assert offer.original_price == 559999.0
    assert offer.installments == "12x $41666.58 sin interés"
