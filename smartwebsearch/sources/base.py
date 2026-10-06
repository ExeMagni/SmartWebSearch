from abc import ABC, abstractmethod

from ..http import PoliteSession
from ..models import Offer


class Source(ABC):
    """Una tienda o marketplace del que obtenemos ofertas."""

    name: str
    full_catalog = False  # True si search() ignora la búsqueda y devuelve todo el catálogo

    def __init__(self, session: PoliteSession | None = None):
        self.session = session or PoliteSession()

    @abstractmethod
    def search(self, query: str, limit: int = 50) -> list[Offer]:
        ...
