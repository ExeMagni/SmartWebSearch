from .base import Source
from .cuyodigital import CuyoDigital
from .mercadolibre import MercadoLibre
from .tecnomovil import TecnoMovil
from .tiendanube import TiendanubeStore, TIENDANUBE_STORES
from .vtex import VtexStore, VTEX_STORES


def available_sources() -> dict[str, Source]:
    sources: dict[str, Source] = {
        "mercadolibre": MercadoLibre(),
        "cuyodigital": CuyoDigital(),
        "tecnomovil": TecnoMovil(),
    }
    for name, base_url in VTEX_STORES.items():
        sources[name] = VtexStore(name, base_url)
    for name, base_url in TIENDANUBE_STORES.items():
        sources[name] = TiendanubeStore(name, base_url)
    return sources


__all__ = [
    "Source", "CuyoDigital", "MercadoLibre", "TecnoMovil",
    "TiendanubeStore", "TIENDANUBE_STORES", "VtexStore", "VTEX_STORES", "available_sources",
]
