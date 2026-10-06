import os
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..models import Offer, Plan
from .base import Source

API_URL = "https://api.mercadolibre.com/sites/MLA/search"
LISTING_URL = "https://listado.mercadolibre.com.ar/{slug}"
CATEGORY_CELULARES = "MLA1055"  # Celulares y Smartphones


class MercadoLibre(Source):
    """MercadoLibre Argentina.

    Si existe la variable de entorno MELI_ACCESS_TOKEN usa la API oficial
    (recomendado: datos estructurados y estables). Si no, cae al listado HTML.
    """

    name = "mercadolibre"

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        token = os.environ.get("MELI_ACCESS_TOKEN")
        if token:
            return self._search_api(query, limit, token)
        return self._search_html(query, limit)

    # --- API oficial -------------------------------------------------------
    def _search_api(self, query: str, limit: int, token: str) -> list[Offer]:
        offers: list[Offer] = []
        offset = 0
        while len(offers) < limit:
            page_size = min(50, limit - len(offers))
            resp = self.session.get(
                API_URL,
                params={
                    "q": query,
                    "category": CATEGORY_CELULARES,
                    "offset": offset,
                    "limit": page_size,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            results = resp.json().get("results", [])
            if not results:
                break
            offers.extend(parse_api_results(results))
            offset += page_size
        return offers[:limit]

    # --- Listado HTML ------------------------------------------------------
    def _search_html(self, query: str, limit: int) -> list[Offer]:
        slug = quote(re.sub(r"\s+", "-", query.strip().lower()))
        resp = self.session.get(LISTING_URL.format(slug=slug))
        if "account-verification" in resp.url:
            raise RuntimeError(
                "MercadoLibre bloqueó el listado (verificación anti-bot). "
                "Configurá MELI_ACCESS_TOKEN para usar la API oficial."
            )
        return parse_listing_html(resp.text)[:limit]


def parse_api_results(results: list[dict]) -> list[Offer]:
    offers = []
    for r in results:
        shipping = r.get("shipping") or {}
        installments = r.get("installments") or {}
        inst = None
        if installments.get("quantity"):
            inst = f"{installments['quantity']}x ${installments.get('amount')}"
            if installments.get("rate") == 0:
                inst += " sin interés"
        offers.append(
            Offer(
                source="mercadolibre",
                title=r.get("title", ""),
                price=r.get("price"),
                original_price=r.get("original_price"),
                currency=r.get("currency_id", "ARS"),
                url=r.get("permalink", ""),
                seller=(r.get("seller") or {}).get("nickname"),
                condition=r.get("condition"),
                free_shipping=shipping.get("free_shipping"),
                installments=inst,
                financing=(
                    [Plan("MercadoPago", installments["quantity"], installments["amount"],
                          installments["quantity"] * installments["amount"])]
                    if installments.get("quantity") and installments.get("amount")
                    else []
                ),
                category="/Celulares y Smartphones/",  # la búsqueda filtra por CATEGORY_CELULARES
            )
        )
    return offers


def _parse_amount(node) -> float | None:
    if node is None:
        return None
    fraction = node.select_one(".andes-money-amount__fraction")
    if fraction is None:
        return None
    value = fraction.get_text(strip=True).replace(".", "")
    cents = node.select_one(".andes-money-amount__cents")
    if cents is not None:
        value += "." + cents.get_text(strip=True)
    try:
        return float(value)
    except ValueError:
        return None


def parse_listing_html(html: str) -> list[Offer]:
    """Parsea el listado de búsqueda (formato "poly-card").

    Los selectores CSS dependen del HTML actual de MercadoLibre y pueden
    romperse cuando cambien el diseño: por eso la API es la opción preferida.
    """
    soup = BeautifulSoup(html, "html.parser")
    offers = []
    for card in soup.select("li.ui-search-layout__item"):
        link = card.select_one("a.poly-component__title") or card.select_one("h3 a, h2 a")
        if link is None:
            continue
        current = card.select_one(".poly-price__current") or card
        previous = card.select_one("s.andes-money-amount--previous")
        installments = card.select_one(".poly-price__installments")
        shipping = card.select_one(".poly-component__shipping")
        seller = card.select_one(".poly-component__seller")
        offers.append(
            Offer(
                source="mercadolibre",
                title=link.get_text(strip=True),
                price=_parse_amount(current),
                original_price=_parse_amount(previous),
                url=link.get("href", "").split("#")[0],
                seller=seller.get_text(strip=True) if seller else None,
                free_shipping=(
                    "gratis" in shipping.get_text().lower() if shipping else None
                ),
                installments=installments.get_text(" ", strip=True) if installments else None,
            )
        )
    return offers
