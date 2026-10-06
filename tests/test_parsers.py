import json
from pathlib import Path

from smartwebsearch.cli import in_category, is_accessory, matches
from smartwebsearch.sources.cuyodigital import parse_bundle
from smartwebsearch.sources.tecnomovil import parse_catalog_html
from smartwebsearch.sources.tiendanube import _ars, parse_search_html
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


def test_vtex_financing_plans():
    products = json.loads((FIXTURES / "vtex_search.json").read_text())
    [offer] = parse_products(products, "oncity")
    assert [(p.installments, p.total) for p in offer.financing] == [(12, 499999.0), (18, 720000.0)]
    assert offer.plan_for(12).total == 499999.0
    assert offer.plan_for(3) is None


def test_cuyodigital_bundle():
    offers = parse_bundle((FIXTURES / "cuyodigital_bundle.js").read_text(encoding="utf-8"))
    assert [o.title for o in offers] == ["Apple iPhone 15 128gb", "Samsung a17 128gb / 4gb", "MacBook Air 13 M3"]
    assert [o.category for o in offers] == ["/Celulares/", "/Celulares/", "/MacBook/"]
    iphone = offers[0]
    assert iphone.price == 1343000
    assert iphone.plan_for(6).total == 6 * 295460
    assert iphone.plan_for(1).methods == "Transferencia"


def test_title_filter():
    assert matches("Celular Samsung Galaxy A56 128 GB Negro", "samsung a56 128gb")
    assert not matches("Reloj SAMSUNG GALAXY FIT 3", "samsung a56")
    assert matches("Teléfono Motorola", "telefono motorola")
    assert not matches("Apple iPhone 17 Pro 256GB", "iphone 17 -pro")
    assert matches("Apple iPhone 17 256GB", "iphone 17 -pro")
    assert not matches("Samsung Galaxy S25 FE 5G 128GB", "samsung s25 -fe")
    assert matches("Teléfono Inteligente Samsung Galaxy S25", "samsung s25 -fe")
    assert not matches("Samsung Galaxy S25 128 GB", "samsung s25 -128gb")
    assert is_accessory("Funda Silicona Samsung A56")
    assert is_accessory("Samsung Galaxy A16 5G Bloqueado Verizon")
    assert not is_accessory("Samsung Galaxy A16 128GB")


def test_category_filter():
    # Rutas reales de las tiendas
    phones = [
        "/Celulares/Celulares Liberados/",                        # fravega
        "/Tecnología/Celulares/Celulares/",                       # oncity
        "/TELEFONIA/CELULARES/",                                  # pardo
        "/Celulares, Teléfonos y Accesorios/Celulares/",          # coppel
        "/Celulares y Telefonía/Celulares/128 GB o más/",         # masonline
        "/TECNOLOGIA/CELULARES Y TABLETS/Celulares/",             # lucianahogar
        None,                                                     # sin dato: no se descarta
    ]
    others = [
        "/Tecnología/Gaming/Monitores gamer/",                    # el monitor "Ls25..."
        "/Celulares/Accesorios para Celulares/Fundas para Celulares/",
        "/Celulares, Teléfonos y Accesorios/Fundas y Accesorios/",
        "/TECNOLOGIA/CELULARES Y TABLETS/Tablets/",
        "/Celulares/Accesorios/",
    ]
    assert all(in_category(p, "celulares") for p in phones)
    assert not any(in_category(p, "celulares") for p in others)
    assert in_category("/Tecnología/Gaming/Monitores gamer/", "monitores")


def test_vtex_price_includes_tax():
    product = {"productName": "X", "link": "", "items": [{"sellers": [{"sellerDefault": True,
        "commertialOffer": {"Price": 909090.08, "Tax": 190908.92, "ListPrice": 1099999.0,
                            "AvailableQuantity": 1, "Installments": []}}]}]}
    [offer] = parse_products([product], "fravega")
    assert offer.price == 1099999.0
    assert offer.original_price is None


def test_tiendanube_search():
    page = (FIXTURES / "tiendanube_search.html").read_text(encoding="utf-8")
    [offer] = parse_search_html(page, "casamendoza")  # el agotado se descarta
    assert offer.title == "Celular Samsung Galaxy A16 128GB 4GB Negro"
    assert offer.category == "/Telefonia/Celulares/"
    assert offer.price == 380000
    assert offer.original_price == 420000
    assert offer.url.endswith("/productos/a16/")
    assert offer.plan_for(1).total == 323000  # descuento efectivo/transferencia
    assert offer.plan_for(6).methods == "MODO"  # el más barato en 6 cuotas
    assert offer.installments == "6x $63333.33 sin interés"
    assert _ars("$544.214,61") == 544214.61


def test_tecnomovil_catalog():
    page = (FIXTURES / "tecnomovil_catalogo.html").read_text(encoding="utf-8")
    [offer] = parse_catalog_html(page)  # la variante "a consultar" se descarta
    assert offer.title == "iPhone 17 256 GB"
    assert offer.price == 1560000
    assert offer.plan_for(6).total == 2496000
    assert offer.url == "https://tecnomovilarg.com/producto/iphone-17"