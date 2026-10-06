from smartwebsearch.models import Offer, Plan
from smartwebsearch.smart import best_option, implicit_rate, monthly_rate, present_value, recommend


def offer(price, *plans):
    return Offer(source="x", title="X", price=price, url="", financing=list(plans))


def test_present_value():
    p = Plan("Visa", 12, 100.0, 1200.0)
    assert present_value(p, 0) == 1200
    assert 1125 < present_value(p, 0.01) < 1126  # 100 × factor de anualidad 11.255
    assert present_value(Plan("Transferencia", 1, 900.0, 900.0), 0.05) == 900  # se paga hoy


def test_monthly_rate():
    assert abs(monthly_rate(21.55) - 0.01771) < 0.0001


def test_interest_free_installments_beat_cash():
    o = offer(1200.0, Plan("Visa", 12, 100.0, 1200.0))
    assert best_option(o, 0.02).plan.installments == 12


def test_cash_discount_beats_expensive_installments():
    # 15% off pagando hoy vs. 6 cuotas con 60% de recargo
    o = offer(1000.0, Plan("Efectivo", 1, 850.0, 850.0), Plan("Tarjeta", 6, 266.67, 1600.0))
    assert best_option(o, 0.02).plan.methods == "Efectivo"


def test_implicit_rate_of_surcharge():
    # 6 cuotas de 160 contra 600 de contado: factor 3.75 ≈ 15.3% mensual
    assert abs(implicit_rate(Plan("Tarjeta", 6, 160.0, 960.0), 600) - 0.1534) < 0.001


def test_recommend_ranks_by_present_value():
    cheap_cash = offer(1000.0)
    interest_free = offer(1050.0, Plan("Visa", 12, 87.5, 1050.0))  # valor hoy < 1000 al 2%
    ranking = recommend([cheap_cash, interest_free], 0.02)
    assert ranking[0].offer is interest_free
