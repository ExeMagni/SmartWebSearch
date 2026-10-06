import csv
import io

from ..models import Offer
from .base import Source
from .tiendanube import _ars

SHEET_ID = "1x1jbj_iCSVWIUlPNKJayLGAFkqSXS6OvkHlrJAIHTI4"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
SKIP = {"vendido", "reservado"}


class TecPhone(Source):
    """TecPhone (Mendoza, @tec_phone.ar). Publica su lista de precios en una
    planilla pública de Google Sheets (link de la bio de Instagram)."""

    name = "tecphone"
    full_catalog = True

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        return parse_sheet_csv(self.session.get(CSV_URL).text)


def _category(section: str) -> str:
    s = section.lower()
    if "ipad" in s:
        return "/Tablets/"
    if "macbook" in s:
        return "/Notebooks/"
    if "watch" in s or "whatch" in s:
        return "/Relojes/"
    return "/Celulares/"  # "iPhone, usados" y "Dispositivos nuevos sellados."


def parse_sheet_csv(text: str) -> list[Offer]:
    """La planilla tiene varias tablas (iPhone usados, nuevos, iPad, MacBook, Watch),
    cada una con un título y su propia fila de encabezado "DISPONIBILIDAD, ..."."""
    offers = []
    section, header = "", None
    for row in csv.reader(io.StringIO(text)):
        first = row[0].strip() if row else ""
        if first.upper() == "DISPONIBILIDAD":
            header = [c.strip().lower() for c in row]
            continue
        if first and not any(c.strip() for c in row[1:]):
            section = first
            continue
        if header is None or not first or first.lower() in SKIP:
            continue
        r = dict(zip(header, (c.strip() for c in row)))
        model = r.get("modelo", "")
        price = _ars(r.get("precio pesos ars"))
        if not model or model.startswith("=") or not price:
            continue
        storage = r.get("almacenamiento") or r.get("ram/gb") or ""
        if storage.isdigit():  # los usados dicen "128" a secas
            storage += " GB"
        notes = [first]
        if r.get("batería"):
            notes.append(f"batería {r['batería']}")
        if "no incluye iva" in r.get("iva", "").lower():
            notes.append("sin IVA")
        usd = r.get("precio usd", "").replace("USD", "").strip()
        if usd:
            notes.append(f"USD {usd}")
        offers.append(
            Offer(
                source="tecphone",
                title=" ".join(x for x in (model, storage, r.get("color", "")) if x),
                price=price,
                url=SHEET_URL,
                seller=f"TecPhone ({', '.join(notes)})",
                condition="used" if "usado" in section.lower() else "new",
                category=_category(section),
            )
        )
    return offers
