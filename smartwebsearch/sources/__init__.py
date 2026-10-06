from .base import Source
from .mercadolibre import MercadoLibre
from .vtex import VtexStore, VTEX_STORES


def available_sources() -> dict[str, Source]:
    sources: dict[str, Source] = {"mercadolibre": MercadoLibre()}
    for name, base_url in VTEX_STORES.items():
        sources[name] = VtexStore(name, base_url)
    return sources


__all__ = ["Source", "MercadoLibre", "VtexStore", "VTEX_STORES", "available_sources"]
