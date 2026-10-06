import json
import re

from ..models import Offer, Plan
from .base import Source

BASE_URL = "https://tecnomovilarg.com"


class TecnoMovil(Source):
    """TecnoMovil (Mendoza). Sitio Next.js: /catalogo trae el catálogo completo
    embebido en el payload de React; lo filtramos localmente en el CLI."""

    name = "tecnomovil"
    full_catalog = True

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        return parse_catalog_html(self.session.get(BASE_URL + "/catalogo").text)


def parse_catalog_html(page: str) -> list[Offer]:
    # ponytail: depende del formato interno de Next.js (self.__next_f.push); si cambia, se rompe.
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', page, re.S)
    payload = "".join(json.loads(f'"{c}"') for c in chunks)
    start = payload.find('{"products":')
    if start < 0:
        raise RuntimeError("No encontré el catálogo en tecnomovilarg.com (¿cambió el sitio?)")
    catalog, _ = json.JSONDecoder().raw_decode(payload, start)

    offers = []
    for p in catalog["products"]:
        for v in p.get("variants", []):
            if v.get("priceOnRequest") or not v.get("priceCash"):
                continue
            plans = []
            if v.get("priceTransfer"):
                plans.append(Plan("Transferencia", 1, v["priceTransfer"], v["priceTransfer"]))
            for inst in v.get("installments", []):
                plans.append(Plan("Tarjeta", inst["count"], inst["each"], inst["total"]))
            storage = v.get("storage") or v.get("capacity") or ""
            offers.append(
                Offer(
                    source="tecnomovil",
                    title=f"{p['name']} {storage}".strip(),
                    price=v["priceCash"],
                    url=f"{BASE_URL}/producto/{p['slug']}",
                    seller="TecnoMovil (efectivo" + (f", USD {v['priceUSD']}" if v.get("priceUSD") else "") + ")",
                    condition="new" if p.get("condition") == "nuevo" else p.get("condition"),
                    financing=plans,
                    category=f"/{p['category']}/" if p.get("category") else None,
                )
            )
    return offers
