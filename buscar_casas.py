#!/usr/bin/env python
"""
buscar_casas.py — Búsqueda y análisis de casas en Mendoza (Godoy Cruz, Luján de Cuyo,
Maipú y Cuarta Sección / Capital) con presupuesto ≤ PRECIO_MAX_USD (25% de ahorro para el crédito BNA).

Funcionalidades:
- Búsqueda en portales inmobiliarios líderes: InMoup y Zonaprop.
- Filtro estricto de seguridad: descarta automáticamente zonas rojas / villas.
- Detección de m² cubiertos vs m² de terreno y cálculo de USD/m² cubierto.
- Clasificación de barrios recomendados y barrios privados/cerrados.
- Generación de informe profesional multipestaña en Excel (casas_mendoza_recomendadas.xlsx).

Uso:
    python buscar_casas.py                     # Ejecuta pipeline completo y genera Excel
    python buscar_casas.py --top 15            # Muestra las mejores 15 oportunidades en consola
    python buscar_casas.py --privados          # Muestra casas en barrios privados/cerrados
    python buscar_casas.py --dept "Godoy Cruz" # Filtra por departamento
    python buscar_casas.py --max-precio 100000 # Filtra por tope de precio
"""

import argparse
import os
import sys
from pathlib import Path

# Aseguramos que el package raíz sea importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reconfigurar codificación en Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pipeline_mendoza_pro import (
    CasaPro,
    PRECIO_MAX_TXT,
    PRECIO_MAX_USD,
    build_excel_workbook,
    harvest_inmoup,
    harvest_zonaprop,
)

ANCHO = 92
SEP = "-" * ANCHO
SEP_DOBLE = "=" * ANCHO

COLOR = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "verde": "\033[32m",
    "azul": "\033[36m",
    "rojo": "\033[31m",
    "gris": "\033[90m",
    "amarillo": "\033[33m",
    "dorado": "\033[38;5;214m",
}


def c(nombre: str, texto: str) -> str:
    if sys.stdout.isatty():
        return COLOR.get(nombre, "") + texto + COLOR["reset"]
    return texto


def fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    return f"USD {v:,.0f}".replace(",", ".")


def fmt_m2(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} m²".replace(",", ".")


def fmt_pm2(v: float | None) -> str:
    if v is None:
        return "—"
    return f"USD {v:,.0f}/m²".replace(",", ".")


def imprimir_casa_card(casa: CasaPro, idx: int):
    print(f"\n{c('bold', f'#{idx:>3}. {casa.titulo}')}")
    print(f"      {c('azul', f'[{casa.departamento}]')} {c('bold', casa.barrio_especifico)}  |  {casa.tipo_urbanizacion}  |  {casa.condicion}")

    cub_str = fmt_m2(casa.m2_cubiertos)
    tot_str = fmt_m2(casa.m2_terreno)
    p_cub_str = fmt_pm2(casa.precio_m2_cubierto)

    dorms = f"{casa.dormitorios} dorm." if casa.dormitorios else ""
    banos = f"{casa.banos} baños" if casa.banos else ""
    coch = f"{casa.cocheras} coch." if casa.cocheras else ""
    specs = " | ".join(filter(None, [dorms, banos, coch]))
    specs_str = f"  ({specs})" if specs else ""

    print(f"      Precio:  {c('verde', fmt_usd(casa.precio_usd))}  |  Cub: {cub_str}  |  Terr: {tot_str}  |  {c('amarillo', p_cub_str)}{specs_str}")
    print(f"      Score:   {c('dorado', casa.score_oportunidad)}  |  {c('gris', casa.justificacion_zona[:70])}")
    print(f"      Link:    {c('gris', casa.url)}  [{casa.portal}]")


def main():
    parser = argparse.ArgumentParser(
        description="Buscador inteligente de casas en zonas recomendadas de Mendoza.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--max-precio", type=float, default=PRECIO_MAX_USD, help=f"Precio maximo en USD (default: {PRECIO_MAX_USD}, 25%% de ahorro para el crédito BNA)")
    parser.add_argument("--dept", type=str, default=None, choices=["Godoy Cruz", "Luján de Cuyo", "Maipú", "Cuarta Sección / Capital"], help="Filtrar por departamento")
    parser.add_argument("--top", type=int, default=None, help="Mostrar solo las Top N mejores oportunidades por precio/m² cubierto")
    parser.add_argument("--privados", action="store_true", help="Mostrar solo casas en barrios privados o cerrados")
    parser.add_argument("--sin-excel", action="store_true", help="No regenerar el archivo Excel")
    args = parser.parse_args()

    print(SEP_DOBLE)
    print(c("bold", "  BUSCADOR DE CASAS EN ZONAS SEGURAS DE MENDOZA (≤ " + PRECIO_MAX_TXT + ")"))
    print(SEP_DOBLE)
    print("  Departamentos: Godoy Cruz, Luján de Cuyo, Maipú, Cuarta Sección / Capital")
    print(f"  Filtro precio: Hasta {fmt_usd(args.max_precio)}")
    print("  Seguridad:     Exclusión automática de Villa Hipódromo, Campo Pappa, La Gloria, etc.")
    print("  Portales:      InMoup + Zonaprop (todas las subzonas)")
    print(SEP)

    print("\nRecolectando propiedades...")
    inmoup_props = harvest_inmoup()
    zonaprop_props = harvest_zonaprop()

    # Deduplicar
    unicas: list[CasaPro] = []
    vistos = set()
    for item in (inmoup_props + zonaprop_props):
        if item.url and item.url not in vistos:
            vistos.add(item.url)
            unicas.append(item)

    # Filtrar por precio y parámetros opcionales
    filtradas = [c for c in unicas if c.precio_usd <= args.max_precio]

    if args.dept:
        filtradas = [c for c in filtradas if c.departamento == args.dept]

    if args.privados:
        filtradas = [c for c in filtradas if c.tipo_urbanizacion == "Barrio Privado/Cerrado"]

    # Ordenar por precio/m2 cubierto (o terreno como fallback)
    filtradas.sort(key=lambda x: (x.precio_m2_cubierto or 9999, x.precio_usd))

    if args.top:
        filtradas = filtradas[:args.top]

    print(f"\n{SEP}")
    print(c("bold", f"  RESULTADOS: {len(filtradas)} propiedades verificadas"))
    print(SEP)

    for i, casa in enumerate(filtradas, 1):
        imprimir_casa_card(casa, i)

    # Generar Excel
    if not args.sin_excel:
        excel_path = os.path.abspath("casas_mendoza_recomendadas.xlsx")
        build_excel_workbook(unicas, excel_path)


if __name__ == "__main__":
    main()
