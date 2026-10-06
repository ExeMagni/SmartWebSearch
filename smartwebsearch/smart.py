"""Recomendación: compara contado vs. cuotas en valor presente.

Una cuota futura vale menos que la misma plata hoy, porque esa plata puede
rendir (plazo fijo) mientras tanto. Descontando cada cuota a una tasa mensual,
todas las formas de pago quedan en "pesos de hoy" y se pueden comparar.
"""

from dataclasses import dataclass

import requests

from .models import Offer, Plan

BCRA_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias"
BCRA_PLAZO_FIJO_30D = 12  # TNA de depósitos a 30 días, en %


@dataclass
class Option:
    offer: Offer
    plan: Plan | None  # None = precio de contado publicado
    present_value: float

    @property
    def nominal(self) -> float:
        return self.plan.total if self.plan else self.offer.price


def fetch_reference_tna() -> tuple[float, str]:
    """Última TNA de plazo fijo a 30 días publicada por el BCRA: (tna %, fecha)."""
    resp = requests.get(BCRA_URL, timeout=20)
    resp.raise_for_status()
    for v in resp.json()["results"]:
        if v.get("idVariable") == BCRA_PLAZO_FIJO_30D:
            return float(v["ultValorInformado"]), v.get("ultFechaInformada", "")
    raise RuntimeError("El BCRA no devolvió la tasa de plazo fijo")


def monthly_rate(tna: float) -> float:
    """TNA en % -> tasa efectiva mensual (convención plazo fijo: 30/365)."""
    return tna / 100 * 30 / 365


def present_value(plan: Plan, rate: float) -> float:
    """1 pago = hoy. N cuotas = la primera al mes (primer resumen de la tarjeta)."""
    if plan.installments <= 1:
        return plan.total
    if rate == 0:
        return plan.installment_value * plan.installments
    n = plan.installments
    return plan.installment_value * (1 - (1 + rate) ** -n) / rate


def implicit_rate(plan: Plan, cash_price: float) -> float:
    """Tasa mensual que te cobran por financiar vs. pagar `cash_price` hoy.

    Es la tasa que hace present_value(plan) == cash_price. Negativa si las
    cuotas en valor presente cuestan menos que el contado aun sin descontar.
    """
    lo, hi = -0.5, 1.0
    for _ in range(100):  # bisección: present_value baja cuando la tasa sube
        mid = (lo + hi) / 2
        if present_value(plan, mid) > cash_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cash_price(offer: Offer) -> float:
    """El mejor precio pagando hoy (contado o descuento por efectivo/transferencia)."""
    return min([offer.price] + [p.total for p in offer.financing if p.installments <= 1])


def best_option(offer: Offer, rate: float) -> Option:
    options = [Option(offer, None, offer.price)]
    options += [Option(offer, p, present_value(p, rate)) for p in offer.financing]
    return min(options, key=lambda o: (o.present_value, -(o.plan.installments if o.plan else 0)))


def recommend(offers: list[Offer], rate: float) -> list[Option]:
    """La mejor forma de pago de cada oferta, de la más conveniente a la menos."""
    return sorted((best_option(o, rate) for o in offers), key=lambda o: o.present_value)
