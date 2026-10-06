import argparse
import csv
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import smart
from .models import Offer
from .sources import available_sources

CONFIG_PATH = Path.home() / ".smartwebsearch.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c) and not c.isspace())


ACCESSORY_WORDS = (
    "funda", "protector", "vidrio", "templado", "carcasa", "cargador", "adaptador",
    "cable", "auricular", "reloj", "smartwatch", "soporte", "lamina", "film",
    "otterbox", "repuesto", "reemplazo",
    "bloqueado",  # equipos importados atados a un operador extranjero
)


def is_accessory(title: str) -> bool:
    title = _normalize(title)
    return any(word in title for word in ACCESSORY_WORDS)


def in_category(path: str | None, wanted: str) -> bool:
    """¿La ruta de categoría de la tienda corresponde a `wanted` (y no a sus accesorios)?

    "/Celulares/Celulares Liberados/" -> sí; "/Celulares/Accesorios/Fundas/" -> no;
    "/Tecnología/Gaming/Monitores gamer/" -> no. Sin categoría conocida, no descartamos.
    """
    if path is None:
        return True
    raw = [s.strip().lower() for s in path.strip("/").split("/")]
    segments = [_normalize(s) for s in raw]
    stem = _normalize(wanted).rstrip("s")  # "celulares" -> "celulare", matchea singular y plural
    # Solo cuentan niveles "puros": "Celulares y Tablets" o "Celulares, Teléfonos y
    # Accesorios" son contenedores mixtos y no alcanzan para decir que es un celular.
    hits = [
        i for i, seg in enumerate(segments)
        if seg.startswith(stem) and not re.search(r",| y | e ", raw[i])
    ]
    if not hits:
        return False
    return not any(
        word in later for later in segments[hits[-1] + 1:]
        for word in ("accesori", "funda", "cargador", "repuesto")
    )


def matches(title: str, query: str) -> bool:
    """Todas las palabras de la búsqueda tienen que aparecer en el título.

    Se comparan sin espacios ni acentos, así "128gb" encuentra "128 GB".
    Una palabra con "-" adelante excluye: "iphone 17 -pro".
    """
    # ponytail: substring simple; "a5" también matchea "a55". Si molesta, pasar a tokens.
    words = query.split()
    include = [_normalize(w) for w in words if not w.startswith("-")]
    exclude = [_normalize(w[1:]) for w in words if w.startswith("-") and len(w) > 1]
    if not all(w in _normalize(title) for w in include):
        return False
    # Excluir es por palabra completa: "-fe" saca "S25 FE" pero no "Teléfono".
    # También se prueban pares de palabras pegadas, así "-128gb" saca "128 GB".
    tokens = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", title.lower()))
    candidates = set(tokens) | {a + b for a, b in zip(tokens, tokens[1:])}
    return not any(w in candidates for w in exclude)


def main(argv: list[str] | None = None) -> int:
    sources = available_sources()
    parser = argparse.ArgumentParser(
        description="Busca ofertas en tiendas de Argentina y recomienda cuál conviene."
    )
    config = load_config()
    default_category = config.get("categoria", "celulares")
    parser.add_argument("query", nargs="?", help='Ej: "samsung a56" o "iphone 15 128gb"')
    parser.add_argument(
        "-k", "--categoria", default=default_category,
        help=f'Categoría a buscar (ahora por defecto: "{default_category}"; ej. "notebooks").'
             ' "todas" no filtra',
    )
    parser.add_argument(
        "--categoria-default", metavar="CATEGORIA",
        help=f"Guarda la categoría por defecto para las próximas búsquedas (en {CONFIG_PATH})",
    )
    parser.add_argument(
        "-s", "--sources", nargs="+", choices=sorted(sources), default=sorted(sources),
        help="Tiendas a consultar (por defecto, todas)",
    )
    parser.add_argument("-n", "--limit", type=int, default=50, help="Resultados por tienda")
    parser.add_argument("--min-price", type=float)
    parser.add_argument("--max-price", type=float)
    parser.add_argument(
        "-c", "--cuotas", type=int,
        help="Comparar financiación en N cuotas: ordena por costo total",
    )
    parser.add_argument(
        "--todo", action="store_true",
        help="No filtrar por título (muestra todo lo que devuelve cada tienda)",
    )
    parser.add_argument(
        "--tasa", type=float,
        help="Tu tasa de oportunidad como TNA en %% (por defecto: plazo fijo 30 días, BCRA)",
    )
    parser.add_argument("--top", type=int, default=15, help="Cuántas recomendaciones mostrar")
    parser.add_argument("-o", "--output", type=Path, help="Archivo .csv o .json de salida")
    args = parser.parse_args(argv)

    if args.categoria_default:
        config["categoria"] = args.categoria_default
        save_config(config)
        print(f'Categoría por defecto: "{args.categoria_default}"', file=sys.stderr)
        if args.query is None:
            return 0
        if args.categoria == default_category:  # sin -k explícito, usar la nueva
            args.categoria = args.categoria_default
    if args.query is None:
        parser.error("falta la búsqueda (ej. \"samsung a56\")")

    def run(name: str) -> list[Offer]:
        try:
            store_query = " ".join(w for w in args.query.split() if not w.startswith("-"))
            found = sources[name].search(store_query, args.limit)
            print(f"[{name}] {len(found)} resultados", file=sys.stderr)
            return found
        except Exception as exc:  # una tienda caída no frena al resto
            print(f"[{name}] error: {exc}", file=sys.stderr)
            return []

    # Cada tienda tiene su propia sesión con pausa, así que en paralelo seguimos siendo amables.
    with ThreadPoolExecutor(max_workers=8) as pool:
        offers = [o for found in pool.map(run, args.sources) for o in found]

    any_category = args.categoria.lower() == "todas"
    offers = [
        o for o in offers
        if o.price is not None
        and (args.todo or matches(o.title, args.query))
        and (args.todo or any_category or (
            in_category(o.category, args.categoria) and not is_accessory(o.title)
        ))
        and (args.min_price is None or o.price >= args.min_price)
        and (args.max_price is None or o.price <= args.max_price)
        and (args.cuotas is None or o.plan_for(args.cuotas))
    ]
    if args.cuotas:
        offers.sort(key=lambda o: o.plan_for(args.cuotas).total)
    else:
        offers.sort(key=lambda o: o.price)

    if args.output:
        write_output(offers, args.output)
        print(f"Guardado en {args.output}", file=sys.stderr)
    elif args.cuotas:
        for o in offers:
            p = o.plan_for(args.cuotas)
            recargo = (p.total / o.price - 1) * 100
            print(
                f"{p.installments:>2}x ${p.installment_value:>10,.0f} = ${p.total:>12,.0f}"
                f" ({recargo:+5.1f}%)  {o.source:<12} {o.title[:50]}  [{p.methods[:40]}]"
            )
    else:
        print_recommendation(offers, args.tasa, args.top)
    return 0


def _describe(option: smart.Option) -> str:
    p = option.plan
    if p is None:
        return "Contado"
    if p.installments <= 1:
        return f"Contado ({p.methods})"
    return f"{p.installments}x ${p.installment_value:,.0f} ({p.methods})"


def print_recommendation(offers: list[Offer], tna: float | None, top: int) -> None:
    if tna is None:
        try:
            tna, fecha = smart.fetch_reference_tna()
            source = f"plazo fijo 30 días, BCRA {fecha}"
        except Exception as exc:
            print(f"No pude obtener la tasa del BCRA ({exc}); usá --tasa. Comparo sin descontar.",
                  file=sys.stderr)
            tna, source = 0.0, "sin tasa"
    else:
        source = "--tasa"
    rate = smart.monthly_rate(tna)
    ranking = smart.recommend(offers, rate)
    if not ranking:
        print("Sin resultados.")
        return

    print(f"\nTasa de referencia: TNA {tna:.2f}% ({source}) = {rate * 100:.2f}% mensual")
    print("'Valor hoy' = lo que realmente te cuesta, con las cuotas descontadas a esa tasa.\n")
    print(f"{'#':>2}  {'Valor hoy':>12}  {'Pagás':>12}  {'Contado':>12}  {'Tienda':<12} Cómo pagar / Producto")
    for i, opt in enumerate(ranking[:top], 1):
        cash = smart.cash_price(opt.offer)
        print(
            f"{i:>2}  ${opt.present_value:>11,.0f}  ${opt.nominal:>11,.0f}  ${cash:>11,.0f}"
            f"  {opt.offer.source:<12} {_describe(opt)[:60]}"
            f"\n{'':>58}{opt.offer.title[:70]}"
        )

    best = ranking[0]
    cash = smart.cash_price(best.offer)
    print(f"\n>> Conviene: {best.offer.title} en {best.offer.source}, pagando {_describe(best)}.")
    print(f"   {best.offer.url}")
    if best.plan and best.plan.installments > 1:
        ahorro = cash - best.present_value
        print(f"   Pagás ${best.nominal:,.0f} en total, que hoy equivalen a ${best.present_value:,.0f}:"
              f" ${ahorro:,.0f} menos que el contado (${cash:,.0f}).")
    # Para la mejor oferta, ¿qué tan caras son sus cuotas con recargo?
    caras = [
        (p, smart.implicit_rate(p, cash)) for p in best.offer.financing
        if p.installments > 1 and p.total > cash * 1.001
    ]
    if caras:
        p, r = min(caras, key=lambda x: x[1])
        verdict = "no conviene" if r > rate else "conviene igual"
        print(f"   Ojo: {p.installments} cuotas con {p.methods} equivalen a un préstamo al"
              f" {r * 100:.1f}% mensual vs. tu tasa {rate * 100:.2f}%: {verdict}.")


def write_output(offers: list[Offer], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [o.to_dict() for o in offers]
    if path.suffix == ".json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        for row in rows:
            row["financing"] = json.dumps(row["financing"], ensure_ascii=False)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(Offer.__dataclass_fields__))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
