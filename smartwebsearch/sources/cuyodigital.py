import re

from ..models import Offer, Plan
from .base import Source

BASE_URL = "https://www.cuyodigital.com"


class CuyoDigital(Source):
    """Cuyo Digital (Mendoza).

    No tiene buscador ni API: el catálogo entero está escrito dentro del
    bundle de JavaScript del sitio. Lo bajamos y filtramos localmente.
    """

    name = "cuyodigital"

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        home = self.session.get(BASE_URL + "/").text
        bundle = re.search(r'src="(/assets/index-[^"]+\.js)"', home)
        if bundle is None:
            raise RuntimeError("No encontré el catálogo en cuyodigital.com (¿cambió el sitio?)")
        offers = parse_bundle(self.session.get(BASE_URL + bundle.group(1)).text)
        # El catálogo es completo: el filtro por la búsqueda lo hace el CLI.
        return offers


def _ars(text: str) -> float | None:
    digits = re.sub(r"[^0-9]", "", text or "")
    return float(digits) if digits else None


def _field(obj: str, name: str) -> str | None:
    m = re.search(name + r":`([^`]*)`", obj)
    return m.group(1) if m else None


def parse_bundle(js: str) -> list[Offer]:
    offers = []
    # Secciones del catálogo ("Celulares", "MacBook"...): cada producto pertenece
    # a la última sección que aparece antes que él en el bundle.
    sections = [
        (m.start(), m.group(1))
        for m in re.finditer(r"\{name:`([^`]+)`,slug:`[^`]+`,image:[^,]+,subcategories:", js)
    ]
    # ponytail: regex sobre JS minificado; se rompe si cambian los nombres de campos.
    for match in re.finditer(r"\{name:`[^{}]*?efectivo:`[^{}]*\}", js):
        obj = match.group(0)
        section = next((name for pos, name in reversed(sections) if pos < match.start()), None)
        price = _ars(_field(obj, "efectivo"))
        if price is None:
            continue
        plans = []
        transfer = _ars(_field(obj, "transferencia"))
        if transfer:
            plans.append(Plan("Transferencia", 1, transfer, transfer))
        cuotas = re.match(r"(\d+) cuotas de \$([\d.]+)", _field(obj, "cuotas") or "")
        if cuotas:
            n, value = int(cuotas.group(1)), _ars(cuotas.group(2))
            plans.append(Plan("Tarjeta", n, value, n * value))
        usd = _field(obj, "usd")
        offers.append(
            Offer(
                source="cuyodigital",
                title=_field(obj, "name"),
                price=price,
                url=BASE_URL,
                seller="Cuyo Digital (efectivo" + (f", USD {usd}" if usd else "") + ")",
                condition="new",
                installments=_field(obj, "cuotas"),
                financing=plans,
                category=f"/{section}/" if section else None,
            )
        )
    return offers
