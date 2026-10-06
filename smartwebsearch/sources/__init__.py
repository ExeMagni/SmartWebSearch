from .base import Source
from .cuyodigital import CuyoDigital
from .gendigital import GenDigital, ocr_available
from .mendofix import Mendofix
from .mercadolibre import MercadoLibre
from .sencomputacion import SenComputacion
from .tecnomovil import TecnoMovil
from .tecphone import TecPhone
from .tiendanube import TiendanubeStore, TIENDANUBE_STORES
from .vtex import VtexStore, VTEX_STORES
from .xiaomistore import XiaomiStore


def available_sources() -> dict[str, Source]:
    sources: dict[str, Source] = {
        "mercadolibre": MercadoLibre(),
        "cuyodigital": CuyoDigital(),
        "tecnomovil": TecnoMovil(),
        "tecphone": TecPhone(),
        "mendofix": Mendofix(),
        "sencomputacion": SenComputacion(),
        "gendigital": GenDigital(),
        "xiaomistore": XiaomiStore(),
    }
    for name, base_url in VTEX_STORES.items():
        sources[name] = VtexStore(name, base_url)
    for name, base_url in TIENDANUBE_STORES.items():
        sources[name] = TiendanubeStore(name, base_url)
    return sources


def default_sources(sources: dict[str, Source]) -> list[str]:
    """Las que corren sin -s: MercadoLibre es a pedido (--mercadolibre, muchos requests)
    y Gen Digital solo si está instalado el OCR."""
    skip = {"mercadolibre"} | (set() if ocr_available() else {"gendigital"})
    return sorted(name for name in sources if name not in skip)


__all__ = [
    "Source", "CuyoDigital", "GenDigital", "Mendofix", "MercadoLibre", "SenComputacion",
    "TecnoMovil", "TecPhone", "TiendanubeStore", "TIENDANUBE_STORES", "VtexStore", "VTEX_STORES",
    "XiaomiStore",
    "available_sources", "default_sources",
]
