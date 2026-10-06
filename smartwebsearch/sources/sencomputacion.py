import re

from ..models import Offer
from .base import Source

BASE_URL = "https://www.sencomputacion.com.ar"
PAGE_SIZE = 12  # la tienda (Empretienda) entrega de a 12 productos
MAX_PAGES = 20


class SenComputacion(Source):
    """SEN Computación. Tienda Empretienda: la página /celulares carga los productos
    por AJAX desde /v4/product/category, que devuelve JSON con precio y stock."""

    name = "sencomputacion"
    full_catalog = True

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        page = self.session.get(BASE_URL + "/celulares").text
        ids = re.search(r"var ids = \[([\d,]+)\]", page)
        if ids is None:
            raise RuntimeError("No encontré la categoría de celulares en sencomputacion.com.ar")
        csrf = re.search(r'csrf_token\s*=\s*"([^"]+)"|name="csrf-token" content="([^"]+)"', page)
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if csrf:
            headers["X-CSRF-TOKEN"] = csrf.group(1) or csrf.group(2)
        products: list[dict] = []
        for n in range(MAX_PAGES):
            data = self.session.get(
                BASE_URL + "/v4/product/category",
                params={"filter_page": n, "filter_order": 2, "filter_categories[]": ids.group(1).split(",")},
                headers=headers,
            ).json()["data"]
            products += data
            if len(data) < PAGE_SIZE:
                break
        return parse_products(products)


def parse_products(products: list[dict]) -> list[Offer]:
    offers = []
    for p in products:
        if not any(s.get("s_cantidad") or s.get("s_ilimitado") for s in p.get("stock", [])):
            continue  # sin stock
        on_sale = p.get("p_oferta") and p.get("p_precio_oferta")
        name = p.get("p_nombre", "").strip()
        offers.append(
            Offer(
                source="sencomputacion",
                title=name,
                price=float(p["p_precio_oferta"] if on_sale else p["p_precio"]),
                original_price=float(p["p_precio"]) if on_sale else None,
                url=f"{BASE_URL}/celulares/{p.get('p_link', '')}",
                seller="SEN Computación",
                condition="used" if "usado" in name.lower() else "new",
                category="/Celulares/",
            )
        )
    return offers
