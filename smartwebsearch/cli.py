import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

from . import smart
from .models import Offer
from .sources import available_sources, default_sources

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
    "cable", "auricular", "buds", "reloj", "watch", "band", "soporte", "lamina", "film",
    "otterbox", "repuesto", "reemplazo",
    "bloqueado",  # equipos importados atados a un operador extranjero
)


def is_accessory(title: str) -> bool:
    title = _normalize(title)
    return any(word in title for word in ACCESSORY_WORDS)


# Precios simbólicos como el plan canje de Frávega ("Cargaste tu iPhone ... Bono", $1).
MIN_REAL_PRICE = 1000

USED_WORDS = ("usado", "reacondicionado", "refurbished", "seminuevo", "openbox")


def is_used(offer: Offer) -> bool:
    """Usado o reacondicionado. Muchas tiendas marcan todo como "new" (Frávega vende
    "Reacondicionado ..." como new), así que también se mira el título."""
    # ponytail: por palabras; un usado sin "usado" en el título ni en la condición pasa por nuevo.
    condition = (offer.condition or "").lower()
    if condition and condition not in ("new", "nuevo"):
        return True
    return any(word in _normalize(offer.title) for word in USED_WORDS)


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
    parser.add_argument(
        "query", nargs="*",
        help='Ej: "samsung a56". Con varias ("samsung s25" "iphone 15 pro max") compara cuál conviene',
    )
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
        "-s", "--sources", nargs="+", choices=sorted(sources), default=default_sources(sources),
        help="Tiendas a consultar (por defecto, todas salvo MercadoLibre)",
    )
    parser.add_argument(
        "--mercadolibre", action="store_true",
        help="Sumar MercadoLibre (API de catálogo con MELI_CLIENT_ID/MELI_CLIENT_SECRET de .env;"
             " es lenta: un request por producto)",
    )
    parser.add_argument("-n", "--limit", type=int, default=50, help="Resultados por tienda")
    estado = parser.add_mutually_exclusive_group()
    estado.add_argument("--nuevo", action="store_true", help="Solo equipos nuevos")
    estado.add_argument("--usado", action="store_true", help="Solo usados o reacondicionados")
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
    parser.add_argument(
        "--top", type=int,
        help="Cuántas recomendaciones mostrar por búsqueda (15; 5 si comparás varias)",
    )
    parser.add_argument("-o", "--output", type=Path, help="Archivo .csv o .json de salida")
    args = parser.parse_args(argv)

    if args.categoria_default:
        config["categoria"] = args.categoria_default
        save_config(config)
        print(f'Categoría por defecto: "{args.categoria_default}"', file=sys.stderr)
        if not args.query:
            return 0
        if args.categoria == default_category:  # sin -k explícito, usar la nueva
            args.categoria = args.categoria_default
    if not args.query:
        parser.error("falta la búsqueda (ej. \"samsung a56\")")
    if args.mercadolibre and "mercadolibre" not in args.sources:
        args.sources.append("mercadolibre")
    compare = len(args.query) > 1
    top = args.top or (5 if compare else 15)

    def run_store(name: str) -> dict[str, list[Offer]]:
        """Todas las búsquedas en una tienda, una tras otra, así se respeta su pausa entre
        requests. Si la tienda baja el catálogo entero, se baja una sola vez."""
        found: dict[str, list[Offer]] = {}
        catalog = None
        for query in args.query:
            if catalog is not None:
                found[query] = catalog
                continue
            label = f'[{name}]' + (f' "{query}"' if compare and not sources[name].full_catalog else "")
            try:
                store_query = " ".join(w for w in query.split() if not w.startswith("-"))
                found[query] = sources[name].search(store_query, args.limit)
                print(f"{label} {len(found[query])} resultados", file=sys.stderr)
            except Exception as exc:  # una tienda caída no frena al resto
                print(f"{label} error: {exc}", file=sys.stderr)
                found[query] = []
            if sources[name].full_catalog:
                catalog = found[query]
        return found

    # Un hilo por tienda: todas trabajan a la vez y cada una va a su ritmo.
    pool = ThreadPoolExecutor(max_workers=len(args.sources))
    futures = [pool.submit(run_store, name) for name in args.sources]
    try:
        # Espera con timeout: en Windows una espera sin timeout no se corta con Ctrl+C.
        while not all(f.done() for f in futures):
            wait(futures, timeout=0.5)
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        pool.shutdown(wait=False, cancel_futures=True)
        os._exit(130)  # los hilos no se pueden interrumpir; salir sin esperar a que terminen
    pool.shutdown()
    per_store = [f.result() for f in futures]

    def collect(query: str) -> list[Offer]:
        offers = [o for found in per_store for o in found[query]]
        any_category = args.categoria.lower() == "todas"
        offers = [
            o for o in offers
            if o.price is not None
            and o.price >= MIN_REAL_PRICE
            and (args.todo or matches(o.title, query))
            and (args.todo or any_category or (
                in_category(o.category, args.categoria) and not is_accessory(o.title)
            ))
            and not (args.nuevo and is_used(o))
            and not (args.usado and not is_used(o))
            and (args.min_price is None or o.price >= args.min_price)
            and (args.max_price is None or o.price <= args.max_price)
            and (args.cuotas is None or o.plan_for(args.cuotas))
        ]
        if args.cuotas:
            offers.sort(key=lambda o: o.plan_for(args.cuotas).total)
        else:
            offers.sort(key=lambda o: o.price)
        return offers

    tna, rate_source = (None, None) if args.output or args.cuotas else reference_tna(args.tasa)
    results: dict[str, list[Offer]] = {}
    for query in args.query:
        if compare:
            print(f"\n===== {query} =====", file=sys.stderr if args.output else sys.stdout)
        offers = results[query] = collect(query)
        if args.output:
            continue
        if args.cuotas:
            for o in offers:
                p = o.plan_for(args.cuotas)
                recargo = (p.total / o.price - 1) * 100
                print(
                    f"{p.installments:>2}x ${p.installment_value:>10,.0f} = ${p.total:>12,.0f}"
                    f" ({recargo:+5.1f}%)  {o.source:<12} {o.title[:50]}  [{p.methods[:40]}]"
                )
        else:
            print_recommendation(offers, tna, rate_source, top)

    if args.output:
        write_output([o for offers in results.values() for o in offers], args.output)
        print(f"Guardado en {args.output}", file=sys.stderr)
    elif compare and not args.cuotas:
        print_comparison(results, smart.monthly_rate(tna))
    return 0


def _describe(option: smart.Option) -> str:
    p = option.plan
    if p is None:
        return "Contado"
    if p.installments <= 1:
        return f"Contado ({p.methods})"
    return f"{p.installments}x ${p.installment_value:,.0f} ({p.methods})"


def reference_tna(tna: float | None) -> tuple[float, str]:
    """La tasa de --tasa o, si no se pasó, la de plazo fijo del BCRA: (tna %, de dónde salió)."""
    if tna is not None:
        return tna, "--tasa"
    try:
        tna, fecha = smart.fetch_reference_tna()
        return tna, f"plazo fijo 30 días, BCRA {fecha}"
    except Exception as exc:
        print(f"No pude obtener la tasa del BCRA ({exc}); usá --tasa. Comparo sin descontar.",
              file=sys.stderr)
        return 0.0, "sin tasa"


def print_comparison(results: dict[str, list[Offer]], rate: float) -> None:
    """La mejor opción de cada búsqueda, de la más conveniente a la menos."""
    best = {q: smart.recommend(offers, rate)[:1] for q, offers in results.items()}
    ranking = sorted(((q, opts[0]) for q, opts in best.items() if opts), key=lambda x: x[1].present_value)
    print("\n===== Comparación: la mejor opción de cada búsqueda =====\n")
    print(f"{'#':>2}  {'Valor hoy':>12}  {'Búsqueda':<22} {'Tienda':<12} Cómo pagar / Producto")
    for i, (query, opt) in enumerate(ranking, 1):
        print(
            f"{i:>2}  ${opt.present_value:>11,.0f}  {query[:22]:<22} {opt.offer.source:<12} {_describe(opt)[:50]}"
            f"\n{'':>51}{opt.offer.title[:70]}"
        )
    missing = [q for q, opts in best.items() if not opts]
    if missing:
        print(f"\nSin resultados: {', '.join(missing)}")
    if not ranking:
        return
    query, winner = ranking[0]
    print(f'\n>> De estas opciones conviene "{query}": {winner.offer.title} en {winner.offer.source},'
          f" pagando {_describe(winner)}.")
    print(f"   {winner.offer.url}")
    if len(ranking) > 1:
        next_query, runner_up = ranking[1]
        diff = runner_up.present_value - winner.present_value
        print(f'   Sale ${diff:,.0f} menos que la siguiente, "{next_query}"'
              f" ({diff / runner_up.present_value * 100:.0f}% menos).")


def print_recommendation(offers: list[Offer], tna: float, source: str, top: int) -> None:
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
