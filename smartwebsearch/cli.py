import argparse
import csv
import json
import sys
from pathlib import Path

from .models import Offer
from .sources import available_sources


def main(argv: list[str] | None = None) -> int:
    sources = available_sources()
    parser = argparse.ArgumentParser(
        description="Busca ofertas de celulares en tiendas de Argentina."
    )
    parser.add_argument("query", help='Ej: "samsung galaxy a55" o "iphone 15 128gb"')
    parser.add_argument(
        "-s", "--sources", nargs="+", choices=sorted(sources), default=sorted(sources),
        help="Tiendas a consultar (por defecto, todas)",
    )
    parser.add_argument("-n", "--limit", type=int, default=50, help="Resultados por tienda")
    parser.add_argument("--min-price", type=float)
    parser.add_argument("--max-price", type=float)
    parser.add_argument("-o", "--output", type=Path, help="Archivo .csv o .json de salida")
    args = parser.parse_args(argv)

    offers: list[Offer] = []
    for name in args.sources:
        try:
            found = sources[name].search(args.query, args.limit)
            print(f"[{name}] {len(found)} resultados", file=sys.stderr)
            offers.extend(found)
        except Exception as exc:  # una tienda caída no frena al resto
            print(f"[{name}] error: {exc}", file=sys.stderr)

    offers = [
        o for o in offers
        if o.price is not None
        and (args.min_price is None or o.price >= args.min_price)
        and (args.max_price is None or o.price <= args.max_price)
    ]
    offers.sort(key=lambda o: o.price)

    if args.output:
        write_output(offers, args.output)
        print(f"Guardado en {args.output}", file=sys.stderr)
    else:
        for o in offers:
            print(f"${o.price:>12,.0f}  {o.source:<13} {o.title[:70]}")
    return 0


def write_output(offers: list[Offer], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [o.to_dict() for o in offers]
    if path.suffix == ".json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(Offer.__dataclass_fields__))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
