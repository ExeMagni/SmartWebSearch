from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone


@dataclass
class Offer:
    """Una oferta de un producto en una tienda."""

    source: str
    title: str
    price: float | None
    url: str
    currency: str = "ARS"
    original_price: float | None = None
    seller: str | None = None
    condition: str | None = None  # "new" / "used"
    free_shipping: bool | None = None
    installments: str | None = None
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return asdict(self)
