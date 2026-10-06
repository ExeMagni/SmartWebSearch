import html
import json
import re

from ..http import PoliteSession
from ..models import Offer, Plan, merge_plans
from .base import Source

# Tiendas en Tiendanube: el listado de búsqueda trae, por producto, un JSON
# (data-variants) con precio, descuento por pago y cuotas por medio de pago.
TIENDANUBE_STORES = {
    "casamendoza": "https://www.casamendoza.com.ar",
    "reig": "https://www.reig.com.ar",
    "lucianahogar": "https://lucianahogar.com.ar",
}

MAX_PAGES = 5


class TiendanubeStore(Source):
    def __init__(self, name: str, base_url: str, session: PoliteSession | None = None):
        super().__init__(session)
        self.name = name
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        offers: list[Offer] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            resp = self.session.get(
                self.base_url + "/search/", params={"q": query, "page": page}
            )
            found = [o for o in parse_search_html(resp.text, self.name) if o.url not in seen]
            if not found:
                break
            seen.update(o.url for o in found)
            offers.extend(found)
            if len(offers) >= limit:
                break
        return offers[:limit]


def _ars(text: str | None) -> float | None:
    """'$544.214,61' -> 544214.61"""
    number = re.sub(r"[^0-9,]", "", text or "").replace(",", ".")
    return float(number) if number else None


def _categories(page: str) -> dict[str, str]:
    """product_id -> "/Telefonia/Celulares/", sacado del JSON de analytics de la página."""
    m = re.search(r"googleItems\s*=\s*(\[.*?\]);", page, re.S)
    if m is None:
        return {}
    paths = {}
    for item in json.loads(m.group(1)):
        info = item.get("info", {})
        parts = [info.get(k) for k in ("item_category", "item_category2", "item_category3")]
        paths[str(item["source"]["product_id"])] = "/" + "".join(f"{p}/" for p in parts if p)
    return paths


def parse_search_html(page: str, source: str) -> list[Offer]:
    categories = _categories(page)
    starts = [m.start() for m in re.finditer(r'<div[^>]+class="[^"]*js-item-product', page)]
    offers = []
    for start, end in zip(starts, starts[1:] + [len(page)]):
        block = page[start:end]
        name = re.search(r'js-item-name[^"]*"[^>]*>([^<]+)<', block)
        link = re.search(r'<a[^>]+href="([^"]+/productos/[^"]+)"', block)
        variants = re.search(r'data-variants="([^"]+)"', block)
        product_id = re.search(r'data-product-id="([^"]+)"', block)
        if not (name and link and variants):
            continue
        variant = json.loads(html.unescape(variants.group(1)))[0]
        if not variant.get("available") or variant.get("price_number") is None:
            continue
        price = variant["price_number"]
        plans = []
        discounted = _ars(variant.get("price_with_payment_discount_short"))
        if discounted and discounted < price:
            plans.append(Plan("Efectivo/Transferencia", 1, discounted, discounted))
        installments = json.loads(variant.get("installments_data") or "{}")
        for method, by_count in installments.items():
            for count, data in by_count.items():
                if int(count) > 1:
                    plans.append(
                        Plan(method, int(count), data["installment_value"], data["total_value"])
                    )
        plans = merge_plans(plans)
        best = max(
            (p for p in plans if p.installments > 1 and p.total <= price),
            key=lambda p: p.installments, default=None,
        )
        offers.append(
            Offer(
                source=source,
                title=html.unescape(name.group(1)).strip(),
                price=price,
                original_price=variant.get("compare_at_price_number"),
                url=link.group(1),
                condition="new",
                installments=(
                    f"{best.installments}x ${best.installment_value} sin interés" if best else None
                ),
                financing=plans,
                category=categories.get(product_id.group(1)) if product_id else None,
            )
        )
    return offers
