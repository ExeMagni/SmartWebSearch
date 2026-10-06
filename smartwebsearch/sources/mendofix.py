import re

from bs4 import BeautifulSoup

from ..models import Offer
from .base import Source

PAGE_URL = "https://mendofix.com/venta-de-iphone/"
DOLAR_URL = "https://dolarapi.com/v1/dolares/blue"


class Mendofix(Source):
    """Mendofix (Mendoza). Página de WordPress/Elementor con precios en USD;
    los pasamos a pesos con el dólar blue (venta) para poder comparar."""

    name = "mendofix"
    full_catalog = True

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        # ponytail: dólar blue como aproximación; la tienda puede usar otra cotización.
        rate = float(self.session.get(DOLAR_URL).json()["venta"])
        return parse_page(self.session.get(PAGE_URL).text, rate)


def parse_page(html: str, usd_rate: float) -> list[Offer]:
    """Cada equipo es un contenedor de Elementor: título (h3) + texto con estado,
    almacenamiento y "USD 450"."""
    soup = BeautifulSoup(html, "html.parser")
    offers = []
    for heading in soup.select("h3.elementor-heading-title"):
        box = heading.find_parent(attrs={"data-element_type": "container"})
        text = box.select_one(".elementor-widget-text-editor") if box else None
        if text is None:
            continue
        # Elementor parte los números en <span>s ("34" "0"), por eso se une sin separador.
        lines = [p.get_text("", strip=True) for p in text.find_all("p")]
        price = next((m for m in (re.match(r"USD\s*([\d.,]+)", l, re.I) for l in lines) if m), None)
        if price is None:
            continue
        usd = float(re.sub(r"[^\d]", "", price.group(1)))
        details = " ".join(l for l in lines if l and not l.upper().startswith("USD"))
        title = f"{heading.get_text(' ', strip=True)} {details}".strip()
        offers.append(
            Offer(
                source="mendofix",
                title=title,
                price=round(usd * usd_rate),
                url=PAGE_URL + (f"#{box['id']}" if box.get("id") else ""),
                seller=f"Mendofix (USD {usd:g}, dólar blue ${usd_rate:g})",
                condition="used" if "usado" in title.lower() else "new",
                category="/Celulares/",
            )
        )
    return offers
