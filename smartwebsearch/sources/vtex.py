from urllib.parse import quote

from ..http import PoliteSession
from ..models import Offer, Plan, merge_plans
from .base import Source

# Muchas tiendas argentinas usan la plataforma VTEX, que expone una API
# pública de catálogo. Agregar una tienda nueva es sumar una línea acá.
VTEX_STORES = {
    "carrefour": "https://www.carrefour.com.ar",
    "oncity": "https://www.oncity.com",
    "fravega": "https://www.fravega.com",
    "cetrogar": "https://www.cetrogar.com.ar",
    "naldo": "https://www.naldo.com.ar",
    "pardo": "https://www.pardo.com.ar",
    "coppel": "https://www.coppel.com.ar",
    "jumbo": "https://www.jumbo.com.ar",
    "vea": "https://www.vea.com.ar",
    "disco": "https://www.disco.com.ar",
    "masonline": "https://www.masonline.com.ar",
    "tecnocompro": "https://www.tecnocompro.com",
}

SEARCH_PATH = "/api/catalog_system/pub/products/search/{query}"
PAGE_SIZE = 50  # máximo permitido por VTEX por request
MAX_PAGES = 4  # la búsqueda es difusa: después de 200 productos ya no aparece lo buscado


class VtexStore(Source):
    def __init__(self, name: str, base_url: str, session: PoliteSession | None = None):
        super().__init__(session)
        self.name = name
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        # Páginas completas y con tope: los productos sin stock se descartan, así que
        # "pedir hasta juntar `limit`" podía recorrer el catálogo entero de a 1 producto.
        offers: list[Offer] = []
        for page in range(MAX_PAGES):
            start = page * PAGE_SIZE
            resp = self.session.get(
                self.base_url + SEARCH_PATH.format(query=quote(query)),
                params={"_from": start, "_to": start + PAGE_SIZE - 1},
            )
            products = resp.json()
            offers.extend(parse_products(products, self.name))
            if len(offers) >= limit or len(products) < PAGE_SIZE:
                break
        return offers[:limit]


def parse_products(products: list[dict], source: str) -> list[Offer]:
    offers = []
    for p in products:
        for item in p.get("items", [])[:1]:
            seller = next(
                (s for s in item.get("sellers", []) if s.get("sellerDefault")),
                (item.get("sellers") or [None])[0],
            )
            if seller is None:
                continue
            co = seller.get("commertialOffer", {})
            if not co.get("AvailableQuantity"):
                continue  # sin stock
            best = None
            for inst in co.get("Installments", []):
                if inst.get("InterestRate") == 0 and inst["NumberOfInstallments"] > 1 and (
                    best is None or inst["NumberOfInstallments"] > best["NumberOfInstallments"]
                ):
                    best = inst
            # Algunos vendedores cargan Price sin IVA y el impuesto aparte en Tax.
            price = co.get("Price")
            if price is not None and co.get("Tax"):
                price = round(price + co["Tax"], 2)
            plans = merge_plans([
                Plan(
                    methods=inst.get("PaymentSystemName", "?"),
                    installments=inst["NumberOfInstallments"],
                    installment_value=inst["Value"],
                    total=inst["TotalValuePlusInterestRate"],
                )
                for inst in co.get("Installments", [])
                if inst["NumberOfInstallments"] > 1  # 1 cuota = precio contado
            ])
            list_price = co.get("ListPrice")
            offers.append(
                Offer(
                    source=source,
                    title=p.get("productName", ""),
                    price=price,
                    original_price=list_price if list_price and list_price != price else None,
                    url=p.get("link", ""),
                    seller=seller.get("sellerName"),
                    condition="new",
                    installments=(
                        f"{best['NumberOfInstallments']}x ${best['Value']} sin interés"
                        if best
                        else None
                    ),
                    financing=plans,
                    category=(p.get("categories") or [None])[0],
                )
            )
    return offers
