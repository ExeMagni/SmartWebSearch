import re

from bs4 import BeautifulSoup

from ..models import Offer, Plan
from .base import Source

BASE_URL = "https://xiaomistore.com.ar"
PAGE_SIZE = 100
MAX_PAGES = 5


class XiaomiStore(Source):
    """Xiaomi Store Argentina. PrestaShop: la búsqueda con ajax=1 devuelve JSON con los
    productos y, aparte, el HTML de las tarjetas (de ahí sale "Agotado" y las cuotas)."""

    name = "xiaomistore"

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        offers: list[Offer] = []
        for page in range(1, MAX_PAGES + 1):
            data = self.session.get(
                BASE_URL + "/index.php",
                params={"controller": "search", "s": query, "ajax": 1,
                        "resultsPerPage": PAGE_SIZE, "page": page},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            ).json()
            offers += parse_search(data)
            if len(offers) >= limit or page >= data.get("pagination", {}).get("pages_count", 1):
                break
        return offers[:limit]


def _cards(rendered: str) -> dict[str, str]:
    """id_product -> texto de su tarjeta."""
    soup = BeautifulSoup(rendered or "", "html.parser")
    cards: dict[str, str] = {}
    for art in soup.select("[data-id-product]"):
        text = art.get_text(" ", strip=True)
        if text:
            cards.setdefault(art["data-id-product"], text)
    return cards


def parse_search(data: dict) -> list[Offer]:
    cards = _cards(data.get("rendered_products", ""))
    offers = []
    for p in data.get("products", []):
        card = cards.get(str(p.get("id_product")), "")
        if re.search(r"\bagotado\b", card, re.I) or not p.get("price_amount"):
            continue  # sin stock
        price = float(p["price_amount"])
        regular = p.get("regular_price_amount")
        plans = []
        cuotas = re.search(r"Hasta (\d+) cuotas sin inter", card, re.I)
        if cuotas:
            n = int(cuotas.group(1))
            plans.append(Plan("Tarjeta", n, price / n, price))
        category = p.get("category_name", "")
        url = p.get("url") or p.get("link", "")
        # El nombre no trae la memoria; la variante por defecto sí, en la URL:
        # ".../#/27-memoria_ram-8_gb/58-memoria_interna-256_gb"
        ram = re.search(r"memoria_ram-(\d+)_(gb|tb)", url)
        storage = re.search(r"memoria_interna-(\d+)_(gb|tb)", url)
        memory = "/".join(f"{m.group(1)}{m.group(2).upper()}" for m in (ram, storage) if m)
        offers.append(
            Offer(
                source="xiaomistore",
                title=f"{p.get('name', '')} {memory}".strip(),
                price=price,
                original_price=float(regular) if p.get("has_discount") and regular else None,
                url=url,
                seller="Xiaomi Store (tienda oficial)",
                condition="new",
                financing=plans,
                category="/Celulares/" if category.lower() == "smartphones" else f"/{category}/",
            )
        )
    return offers
