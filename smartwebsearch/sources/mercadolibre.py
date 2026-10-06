import os
import re
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from ..models import Offer
from .base import Source

API = "https://api.mercadolibre.com"
LISTING_URL = "https://listado.mercadolibre.com.ar/{slug}"
DOMAIN_CELULARES = "MLA-CELLPHONES"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _env(name: str) -> str | None:
    """Variable de entorno o, si no está, la línea NAME=valor del .env del proyecto."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name and not key.lstrip().startswith("#"):
                return value.strip().strip("\"'") or None
    except OSError:
        pass
    return None


class MercadoLibre(Source):
    """MercadoLibre Argentina.

    Con MELI_CLIENT_ID y MELI_CLIENT_SECRET (en el entorno o en .env) usa el
    catálogo de la API oficial. /sites/MLA/search da 403 a las apps comunes
    desde 2025, así que se busca en /products/search y se piden las ofertas de
    cada producto. Sin credenciales cae al listado HTML (suele bloquearlo un antibot).
    """

    name = "mercadolibre"

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        token = _env("MELI_ACCESS_TOKEN") or self._client_token()
        if token:
            return self._search_catalog(query, limit, token)
        return self._search_html(query, limit)

    # --- API oficial (catálogo) ---------------------------------------------
    def _client_token(self) -> str | None:
        client_id, secret = _env("MELI_CLIENT_ID"), _env("MELI_CLIENT_SECRET")
        if not (client_id and secret):
            return None
        resp = requests.post(
            f"{API}/oauth/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
            headers={"Accept": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _search_catalog(self, query: str, limit: int, token: str) -> list[Offer]:
        headers = {"Authorization": f"Bearer {token}"}
        products = self.session.get(
            f"{API}/products/search",
            params={"site_id": "MLA", "status": "active", "q": query, "limit": 50,
                    "domain_id": DOMAIN_CELULARES},  # sin esto, para iPhone vienen solo fundas
            headers=headers,
        ).json().get("results", [])
        offers: list[Offer] = []
        # ponytail: un request por producto (con la pausa de PoliteSession); muchos
        # productos del catálogo no tienen ofertas activas y responden 404.
        for product in products:
            if len(offers) >= limit:
                break
            if product.get("domain_id") != DOMAIN_CELULARES:
                continue
            try:
                items = self.session.get(
                    f"{API}/products/{product['id']}/items", headers=headers
                ).json().get("results", [])
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    continue
                raise
            offers.extend(parse_catalog_items(product, items))
        return offers[:limit]

    # --- Listado HTML ------------------------------------------------------
    def _search_html(self, query: str, limit: int) -> list[Offer]:
        slug = quote(re.sub(r"\s+", "-", query.strip().lower()))
        resp = self.session.get(LISTING_URL.format(slug=slug))
        if "account-verification" in resp.url:
            raise RuntimeError(
                "MercadoLibre bloqueó el listado (verificación anti-bot). "
                "Cargá MELI_CLIENT_ID y MELI_CLIENT_SECRET en .env para usar la API oficial."
            )
        return parse_listing_html(resp.text)[:limit]


def parse_catalog_items(product: dict, items: list[dict]) -> list[Offer]:
    """Ofertas de /products/{id}/items. El título sale del producto de catálogo."""
    offers = []
    for it in items:
        item_id = it.get("item_id", "")
        city = ((it.get("seller_address") or {}).get("city") or {}).get("name")
        offers.append(
            Offer(
                source="mercadolibre",
                title=product.get("name", ""),
                price=it.get("price"),
                original_price=it.get("original_price"),
                currency=it.get("currency_id", "ARS"),
                url=f"https://articulo.mercadolibre.com.ar/{item_id[:3]}-{item_id[3:]}",
                seller=f"vendedor {it.get('seller_id')}" + (f" ({city})" if city else ""),
                condition=it.get("condition"),
                free_shipping=(it.get("shipping") or {}).get("free_shipping"),
                category="/Celulares/",  # solo pedimos productos del dominio MLA-CELLPHONES
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
