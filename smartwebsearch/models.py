from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone


@dataclass
class Plan:
    """Una forma de pago: N cuotas de un valor, con uno o más medios de pago."""

    methods: str  # ej. "Visa, Mastercard" o "Efectivo"
    installments: int
    installment_value: float
    total: float


def merge_plans(plans: list[Plan]) -> list[Plan]:
    """Une planes idénticos de distintos medios de pago (Visa/Master/Amex suelen coincidir)."""
    merged: dict[tuple, Plan] = {}
    for p in plans:
        key = (p.installments, round(p.total))
        if key in merged:
            if p.methods not in merged[key].methods.split(", "):
                merged[key].methods += ", " + p.methods
        else:
            merged[key] = Plan(p.methods, p.installments, p.installment_value, p.total)
    return sorted(merged.values(), key=lambda p: (p.installments, p.total))


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
    financing: list[Plan] = field(default_factory=list)
    category: str | None = None  # ruta de la tienda, ej. "/Celulares/Celulares Liberados/"
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return asdict(self)

    def plan_for(self, n: int) -> Plan | None:
        """El plan más barato en exactamente n cuotas."""
        plans = [p for p in self.financing if p.installments == n]
        return min(plans, key=lambda p: p.total, default=None)
