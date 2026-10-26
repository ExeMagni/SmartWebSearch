"""
generar_excel_mendoza.py

Scrapes InMoup y Zonaprop para casas <= USD 150.000 en:
- Godoy Cruz
- Luján de Cuyo
- Maipú
- Cuarta Sección / Capital

Aplica filtro estricto de zonas peligrosas y genera un archivo Excel
'casas_mendoza_recomendadas.xlsx' profesional con enlaces clickeables,
estadísticas y guía de zonas.
"""

import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from smartwebsearch.http import PoliteSession
from smartwebsearch.sources.inmoup import (
    MENDOZA_ZONAS,
    ZONAS_EXCLUIDAS,
    Propiedad,
    _is_zona_excluida,
    _normalize_str,
    scrape_zona as scrape_inmoup_zona,
)

# Reconfigurar encoding para consola Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


@dataclass
class ItemCasa:
    portal: str
    departamento: str
    barrio_zona: str
    titulo: str
    precio_usd: float
    m2_cubiertos: Optional[float]
    m2_totales: Optional[float]
    precio_por_m2: Optional[float]
    direccion: str
    url: str
    por_que_recomendada: str


def classify_departamento(texto: str, default_dept: str = "") -> str:
    t = _normalize_str(texto)
    if "cuarta seccion" in t or "4ta seccion" in t or "capital" in t or "ciudad" in t:
        return "Cuarta Sección / Capital"
    if "godoy cruz" in t or "bombal sur" in t or "trapiche" in t or "fuchs" in t:
        return "Godoy Cruz"
    if "lujan" in t or "carrodilla" in t or "drummond" in t or "vistalba" in t or "chacras" in t:
        return "Luján de Cuyo"
    if "maipu" in t or "luzuriaga" in t or "gutierrez" in t or "torreon" in t:
        return "Maipú"
    return default_dept or "Gran Mendoza"


def classify_barrio(texto: str, dept: str) -> tuple[str, str]:
    t = _normalize_str(texto)

    if dept == "Godoy Cruz":
        if "bombal" in t:
            return "Bombal Sur", "Zona residencial premium, muy segura y de alta cotización pegada a Capital."
        if "trapiche" in t:
            return "Barrio Trapiche", "Barrio consolidado muy buscado, familiar, cerca de ciclovía y Parque Benegas."
        if "fuchs" in t:
            return "Barrio Fuchs", "Barrio residencial tradicional con excelente centro comercial propio y seguridad."
        if "bancario" in t:
            return "Barrio Bancario", "Entorno muy tranquilo, arbolado y excelente acceso a transporte y servicios."
        if "villa marini" in t or "marini" in t:
            return "Villa Marini / Casino", "Zona residencial clásica de casas bajas, segura y muy próxima al centro."
        if "san vicente" in t or "plaza" in t or "centro" in t:
            return "Godoy Cruz Centro / San Vicente", "Ubicación céntrica con todos los servicios, comercios y constante patrullaje."
        return "Godoy Cruz Residencial", "Sector urbano céntrico/este consolidado, de fácil acceso y servicios completos."

    elif dept == "Luján de Cuyo":
        if "carrodilla" in t:
            return "Carrodilla", "Muy buscada por su conexión directa rápida a Godoy Cruz y Capital por Acceso Sur."
        if "drummond" in t:
            return "Mayor Drummond", "Barrio residencial tranquilo con entorno de viñedos y ambiente campestre seguro."
        if "chacras" in t:
            return "Chacras de Coria", "Zona de categoría, arbolada, microclima y gran oferta gastronómica y de servicios."
        if "vistalba" in t:
            return "Vistalba", "Zona residencial abierta y semicerrada, microclima y vistas a la cordillera."
        if "puntilla" in t:
            return "La Puntilla", "Zona residencial estratégica junto a Palmares Open Mall y Corredor del Oeste."
        if "centro" in t or "saenz pena" in t or "plaza" in t:
            return "Luján Centro", "Ubicación céntrica con todos los comercios, servicios y transporte."
        return "Luján Residencial", "Sector residencial de Luján con excelente tranquilidad y terreno amplio."

    elif dept == "Maipú":
        if "luzuriaga" in t or "cardenal" in t or "gonzalez galino" in t:
            return "Luzuriaga", "Zona muy demandada por cercanía al Metrotranvía, plazas y rápida salida a Capital."
        if "torreon" in t or "gabrielli" in t:
            return "El Torreón / Urquiza", "Zona moderna de gran crecimiento, barrios privados, clubes y colegios."
        if "ferroviario" in t:
            return "Barrio Ferroviario (Luzuriaga)", "Barrio residencial cerrado/organizado, seguro y con fácil movilidad."
        if "gutierrez" in t:
            return "Gutiérrez Residencial", "Sector tradicional con identidad barrial, bodegas y buena conectividad."
        if "terrada" in t or "ayres de terrada" in t:
            return "Terrada / Bo Privado", "Emprendimientos modernos y barrios cerrados familiares con seguridad."
        if "irigoyen" in t or "rivadavia" in t or "centro" in t:
            return "Maipú Centro", "Zona céntrica con bancos, plaza principal y servicios integrales."
        return "Maipú Residencial", "Sector residencial de Maipú consolidado y tranquilo."

    else:  # Cuarta Sección / Capital
        if "cuarta oeste" in t or "4ta oeste" in t or "parque central" in t:
            return "Cuarta Sección Oeste", "Sector residencial preferido de la 4ta, seguro, amplio y junto al Parque Central."
        if "cuarta" in t or "4ta" in t:
            return "Cuarta Sección", "Barrio céntrico tradicional, casas de estilo, cercano al microcentro y comercios."
        if "lavalle" in t or "olascoaga" in t or "roca" in t or "capital" in t:
            return "Capital Residencial", "Ubicación estratégica urbana, seguridad céntrica y excelente conectividad."
        return "Cuarta Sección / Capital", "Zona residencial céntrica con gran conectividad y servicios."

    return f"{dept} Residencial", "Barrio abierto residencial estándar verificado fuera de zonas de conflicto."


def scrape_zonaprop_dept(url_slug: str, dept_nombre: str) -> list[ItemCasa]:
    session = PoliteSession()
    items: list[ItemCasa] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
    }

    # Revisamos páginas 1 y 2
    for page in [1, 2]:
        if page == 1:
            url = f"https://www.zonaprop.com.ar/{url_slug}.html"
        else:
            url = f"https://www.zonaprop.com.ar/{url_slug}-pagina-{page}.html"

        try:
            resp = session.get(url, headers=headers, timeout=12)
            if resp.status_code != 200:
                continue

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            postings = soup.find_all(attrs={"data-qa": "posting PROPERTY"})

            for p in postings:
                # Precio
                price_tag = p.find(attrs={"data-qa": "POSTING_CARD_PRICE"})
                price_txt = price_tag.get_text(strip=True) if price_tag else ""
                m_p = re.search(r"USD\s*([\d\.]+)", price_txt)
                if not m_p:
                    continue
                precio = float(m_p.group(1).replace(".", ""))
                if precio > 150_000 or precio < 20_000:
                    continue

                # Localización y título
                loc_tag = p.find(attrs={"data-qa": "POSTING_CARD_LOCATION"})
                loc_txt = loc_tag.get_text(" ", strip=True) if loc_tag else ""

                desc_tag = p.find(attrs={"data-qa": "POSTING_CARD_DESCRIPTION"})
                desc_txt = desc_tag.get_text(" ", strip=True) if desc_tag else ""

                title_tag = p.find(attrs={"data-qa": "POSTING_CARD_TITLE"})
                title_txt = title_tag.get_text(" ", strip=True) if title_tag else desc_txt[:90]

                texto_completo = f"{title_txt} {loc_txt} {desc_txt}"

                # Filtro de zonas de riesgo
                excluida, razon = _is_zona_excluida(texto_completo)
                if excluida:
                    continue

                # m²
                feat_tag = p.find(attrs={"data-qa": "POSTING_CARD_FEATURES"})
                feat_txt = feat_tag.get_text(" ", strip=True) if feat_tag else ""

                m_tot = re.search(r"(\d+)\s*m²\s*tot", feat_txt, re.I)
                m_cub = re.search(r"(\d+)\s*m²\s*cub", feat_txt, re.I)

                m2_tot = float(m_tot.group(1)) if m_tot else None
                m2_cub = float(m_cub.group(1)) if m_cub else None

                if not m2_cub and not m2_tot:
                    # fallback a buscar cualquier m2
                    m_gen = re.search(r"(\d+)\s*m²", feat_txt, re.I)
                    if m_gen:
                        m2_cub = float(m_gen.group(1))

                # Precio / m2
                ref_m2 = m2_cub or m2_tot
                pm2 = round(precio / ref_m2, 0) if ref_m2 and ref_m2 > 10 else None

                # URL
                href = p.get("data-to-posting", "")
                if not href:
                    a_tag = p.find("a", href=True)
                    if a_tag:
                        href = a_tag["href"]
                clean_url = ("https://www.zonaprop.com.ar" + href.split("?")[0]) if href else ""

                dept = classify_departamento(texto_completo, default_dept=dept_nombre)
                barrio, razon_rec = classify_barrio(texto_completo, dept)

                items.append(ItemCasa(
                    portal="Zonaprop",
                    departamento=dept,
                    barrio_zona=barrio,
                    titulo=title_txt[:100],
                    precio_usd=precio,
                    m2_cubiertos=m2_cub,
                    m2_totales=m2_tot,
                    precio_por_m2=pm2,
                    direccion=loc_txt,
                    url=clean_url,
                    por_que_recomendada=razon_rec,
                ))
        except Exception as e:
            print(f"[Zonaprop] Error en {url}: {e}")

    return items


def scrape_all_inmoup() -> list[ItemCasa]:
    subzonas = [
        ("casas-en-venta-en-godoy-cruz", "Godoy Cruz"),
        ("casas-en-venta-en-bombal", "Godoy Cruz"),
        ("casas-en-venta-en-carrodilla", "Luján de Cuyo"),
        ("casas-en-venta-en-mayor-drummond", "Luján de Cuyo"),
        ("casas-en-venta-en-chacras-de-coria", "Luján de Cuyo"),
        ("casas-en-venta-en-lujan-de-cuyo", "Luján de Cuyo"),
        ("casas-en-venta-en-maipu", "Maipú"),
        ("casas-en-venta-en-luzuriaga", "Maipú"),
        ("casas-en-venta-en-gutierrez", "Maipú"),
        ("casas-en-venta-en-cuarta-seccion", "Cuarta Sección / Capital"),
        ("casas-en-venta-en-mendoza", "Cuarta Sección / Capital"),
    ]

    items: list[ItemCasa] = []
    session = PoliteSession()

    for slug, dept_default in subzonas:
        try:
            props = scrape_inmoup_zona(slug, session=session, max_precio_usd=150_000)
            for p in props:
                if p.excluida or not p.precio_usd or p.precio_usd < 20_000:
                    continue

                texto_completo = f"{p.titulo} {p.ubicacion} {p.descripcion}"
                dept = classify_departamento(texto_completo, default_dept=dept_default)
                barrio, razon_rec = classify_barrio(texto_completo, dept)

                items.append(ItemCasa(
                    portal="InMoup",
                    departamento=dept,
                    barrio_zona=barrio,
                    titulo=p.titulo[:100],
                    precio_usd=p.precio_usd,
                    m2_cubiertos=p.m2_cubiertos,
                    m2_totales=p.m2_totales,
                    precio_por_m2=p.precio_por_m2,
                    direccion=p.ubicacion,
                    url=p.url,
                    por_que_recomendada=razon_rec,
                ))
        except Exception as e:
            print(f"[InMoup] Error en {slug}: {e}")

    return items


def main():
    print("=" * 80)
    print("  BUSQUEDA Y EXPORTACION DE CASAS EN ZONAS RECOMENDADAS DE MENDOZA")
    print("=" * 80)

    print("\n[1/3] Scrapeando InMoup...")
    inmoup_items = scrape_all_inmoup()
    print(f"      -> {len(inmoup_items)} propiedades obtenidas de InMoup")

    print("\n[2/3] Scrapeando Zonaprop...")
    zp_configs = [
        ("casas-venta-godoy-cruz-hasta-150000-dolar", "Godoy Cruz"),
        ("casas-venta-lujan-de-cuyo-hasta-150000-dolar", "Luján de Cuyo"),
        ("casas-venta-maipu-hasta-150000-dolar", "Maipú"),
        ("casas-venta-cuarta-seccion-hasta-150000-dolar", "Cuarta Sección / Capital"),
    ]
    zonaprop_items: list[ItemCasa] = []
    for slug, dept in zp_configs:
        zp_items = scrape_zonaprop_dept(slug, dept)
        zonaprop_items.extend(zp_items)
        print(f"      -> {len(zp_items)} de Zonaprop ({dept})")

    # Unir y deduplicar por URL
    todos = inmoup_items + zonaprop_items
    vistos = set()
    unicos: list[ItemCasa] = []
    for it in todos:
        if it.url and it.url not in vistos:
            vistos.add(it.url)
            unicos.append(it)

    print(f"\n[OK] Total casas recolectadas deduplicadas: {len(unicos)}")

    # Ordenar por Departamento y luego por Precio / m²
    dept_order = {
        "Godoy Cruz": 1,
        "Luján de Cuyo": 2,
        "Maipú": 3,
        "Cuarta Sección / Capital": 4,
    }
    unicos.sort(key=lambda x: (dept_order.get(x.departamento, 99), x.precio_por_m2 or float("inf"), x.precio_usd))

    print("\n[3/3] Generando archivo Excel 'casas_mendoza_recomendadas.xlsx'...")
    wb = openpyxl.Workbook()

    # ── Hoja 1: Propiedades Recomendadas ──────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Casas Recomendadas"

    # Estilos
    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")  # Azul noche elegante
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    zebra_fill = PatternFill(start_color="F7F9FC", end_color="F7F9FC", fill_type="solid")
    border_thin = Border(
        left=Side(style="thin", color="D3D3D3"),
        right=Side(style="thin", color="D3D3D3"),
        top=Side(style="thin", color="D3D3D3"),
        bottom=Side(style="thin", color="D3D3D3"),
    )
    link_font = Font(name="Calibri", size=10, color="0044CC", underline="single")
    bold_font = Font(name="Calibri", size=10, bold=True)
    normal_font = Font(name="Calibri", size=10)

    # Título en la hoja
    ws1.merge_cells("A1:K1")
    title_cell = ws1["A1"]
    title_cell.value = "CASAS EN VENTA EN MENDOZA — ZONAS RECOMENDADAS (≤ USD 150.000)"
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="1B365D")
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws1.row_dimensions[1].height = 28

    # Subtítulo explicativo
    ws1.merge_cells("A2:K2")
    sub_cell = ws1["A2"]
    sub_cell.value = "Filtrado automático de zonas de riesgo (Villa Hipódromo, Campo Pappa, La Gloria, etc.) | Portales: InMoup y Zonaprop"
    sub_cell.font = Font(name="Calibri", size=10, italic=True, color="555555")
    ws1.row_dimensions[2].height = 18

    # Fila vacía en fila 3

    # Encabezados en fila 4
    headers = [
        "#",
        "Departamento",
        "Barrio / Zona",
        "Precio (USD)",
        "M² Cubiertos",
        "M² Totales",
        "USD / M²",
        "Título / Ubicación",
        "Por qué se recomienda",
        "Portal",
        "Link a la Propiedad",
    ]

    ws1.row_dimensions[4].height = 26
    for col_idx, h in enumerate(headers, 1):
        cell = ws1.cell(row=4, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border_thin

    # Escribir filas
    for row_idx, item in enumerate(unicos, 5):
        ws1.row_dimensions[row_idx].height = 22
        fill = zebra_fill if row_idx % 2 == 0 else PatternFill(fill_type=None)

        # 1. #
        c1 = ws1.cell(row=row_idx, column=1, value=row_idx - 4)
        c1.alignment = Alignment(horizontal="center", vertical="center")

        # 2. Departamento
        c2 = ws1.cell(row=row_idx, column=2, value=item.departamento)
        c2.font = bold_font
        c2.alignment = Alignment(horizontal="left", vertical="center")

        # 3. Barrio / Zona
        c3 = ws1.cell(row=row_idx, column=3, value=item.barrio_zona)
        c3.alignment = Alignment(horizontal="left", vertical="center")

        # 4. Precio USD
        c4 = ws1.cell(row=row_idx, column=4, value=item.precio_usd)
        c4.number_format = '"USD "#,##0'
        c4.font = bold_font
        c4.alignment = Alignment(horizontal="right", vertical="center")

        # 5. M2 Cubiertos
        c5 = ws1.cell(row=row_idx, column=5, value=item.m2_cubiertos or "—")
        if item.m2_cubiertos:
            c5.number_format = '#,##0" m²"'
        c5.alignment = Alignment(horizontal="right", vertical="center")

        # 6. M2 Totales
        c6 = ws1.cell(row=row_idx, column=6, value=item.m2_totales or "—")
        if item.m2_totales:
            c6.number_format = '#,##0" m²"'
        c6.alignment = Alignment(horizontal="right", vertical="center")

        # 7. USD / M2
        c7 = ws1.cell(row=row_idx, column=7, value=item.precio_por_m2 or "—")
        if item.precio_por_m2:
            c7.number_format = '"USD "#,##0"/m²"'
            c7.font = bold_font
        c7.alignment = Alignment(horizontal="right", vertical="center")

        # 8. Titulo / Ubicacion
        info = f"{item.titulo} ({item.direccion})" if item.direccion else item.titulo
        c8 = ws1.cell(row=row_idx, column=8, value=info[:110])
        c8.alignment = Alignment(horizontal="left", vertical="center")

        # 9. Por qué se recomienda
        c9 = ws1.cell(row=row_idx, column=9, value=item.por_que_recomendada)
        c9.alignment = Alignment(horizontal="left", vertical="center")

        # 10. Portal
        c10 = ws1.cell(row=row_idx, column=10, value=item.portal)
        c10.alignment = Alignment(horizontal="center", vertical="center")

        # 11. Link
        c11 = ws1.cell(row=row_idx, column=11)
        if item.url:
            c11.value = f"Ver en {item.portal}"
            c11.hyperlink = item.url
            c11.font = link_font
        else:
            c11.value = "—"
        c11.alignment = Alignment(horizontal="center", vertical="center")

        # Aplicar bordes y relleno
        for c in [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11]:
            if fill.fill_type:
                c.fill = fill
            c.border = border_thin

    # Habilitar autofiltro
    last_row = len(unicos) + 4
    ws1.auto_filter.ref = f"A4:K{last_row}"

    # Autoajustar ancho de columnas
    col_widths = {
        "A": 6,
        "B": 24,
        "C": 26,
        "D": 15,
        "E": 14,
        "F": 14,
        "G": 16,
        "H": 46,
        "I": 46,
        "J": 12,
        "K": 18,
    }
    for col_letter, width in col_widths.items():
        ws1.column_dimensions[col_letter].width = width

    # ── Hoja 2: Resumen por Departamento ──────────────────────────────────────────
    ws2 = wb.create_sheet(title="Resumen y Precios M2")
    ws2.row_dimensions[1].height = 28
    t2 = ws2["A1"]
    t2.value = "ESTADISTICAS DE PRECIO Y PRECIO/M² POR DEPARTAMENTO"
    t2.font = Font(name="Calibri", size=13, bold=True, color="1B365D")

    summary_headers = [
        "Departamento",
        "Casas Encontradas",
        "Precio Mínimo (USD)",
        "Precio Mediana (USD)",
        "Precio Máximo (USD)",
        "Mediana USD/M²",
        "Rango USD/M²",
        "Barrios Recomendados Clave",
    ]
    ws2.row_dimensions[3].height = 24
    for i, h in enumerate(summary_headers, 1):
        c = ws2.cell(row=3, column=i, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border_thin

    import statistics
    dept_groups = {}
    for it in unicos:
        dept_groups.setdefault(it.departamento, []).append(it)

    dept_highlights = {
        "Godoy Cruz": "Bombal Sur, Trapiche, Fuchs, Bancario, Villa Marini, Centro/San Vicente",
        "Luján de Cuyo": "Carrodilla Centro, Mayor Drummond, Vistalba, La Puntilla, Luján Centro",
        "Maipú": "Luzuriaga (Metrotranvía), El Torreón / Urquiza, Bº Ferroviario, Gutiérrez, Terrada",
        "Cuarta Sección / Capital": "Cuarta Sección Oeste (Parque Central), Eje San Martín/España, Centro",
    }

    row_s = 4
    for dept_name in ["Godoy Cruz", "Luján de Cuyo", "Maipú", "Cuarta Sección / Capital"]:
        items_d = dept_groups.get(dept_name, [])
        if not items_d:
            continue

        prices = [x.precio_usd for x in items_d if x.precio_usd]
        pm2s = [x.precio_por_m2 for x in items_d if x.precio_por_m2]

        ws2.row_dimensions[row_s].height = 22
        fill_s = zebra_fill if row_s % 2 == 0 else PatternFill(fill_type=None)

        vals = [
            dept_name,
            len(items_d),
            min(prices) if prices else 0,
            statistics.median(prices) if prices else 0,
            max(prices) if prices else 0,
            statistics.median(pm2s) if pm2s else 0,
            f"USD {min(pm2s):,.0f} - {max(pm2s):,.0f}".replace(",", ".") if pm2s else "—",
            dept_highlights.get(dept_name, "Zonas residenciales consolidadas"),
        ]

        for col_idx, v in enumerate(vals, 1):
            cell = ws2.cell(row=row_s, column=col_idx, value=v)
            cell.border = border_thin
            if fill_s.fill_type:
                cell.fill = fill_s

            if col_idx in [3, 4, 5]:
                cell.number_format = '"USD "#,##0'
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx == 6:
                cell.number_format = '"USD "#,##0"/m²"'
                cell.font = bold_font
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx in [1, 7, 8]:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")

        row_s += 1

    summary_widths = {"A": 26, "B": 18, "C": 20, "D": 20, "E": 20, "F": 18, "G": 22, "H": 60}
    for col_letter, width in summary_widths.items():
        ws2.column_dimensions[col_letter].width = width

    # ── Hoja 3: Guía de Zonas (Evitar vs Recomendadas) ─────────────────────────────
    ws3 = wb.create_sheet(title="Guía de Zonas y Seguridad")
    ws3.row_dimensions[1].height = 28
    t3 = ws3["A1"]
    t3.value = "GUIA DE ZONAS DE MENDOZA: RECOMENDADAS VS. A EVITAR"
    t3.font = Font(name="Calibri", size=13, bold=True, color="1B365D")

    guide_headers = ["Departamento", "Zonas / Barrios Recomendados (Seguras)", "Zonas a Evitar (Riesgo / Villas)", "Recomendación para Comprador"]
    ws3.row_dimensions[3].height = 24
    for i, h in enumerate(guide_headers, 1):
        c = ws3.cell(row=3, column=i, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border_thin

    guide_rows = [
        (
            "Godoy Cruz",
            "• Bombal Sur (categoría alta, seguro, arbolado)\n• Barrio Trapiche (entorno Parque Benegas, ciclovía)\n• Barrio Fuchs (consolidado, centro comercial propio)\n• Barrio Bancario (tranquilo, familiar)\n• Villa Marini y Centro cívico/San Vicente",
            "• Villa Hipódromo (oeste/sur del hipódromo)\n• Campo Pappa y La Estanzuela alta\n• Barrio La Gloria (sureste, límite con Maipú)\n• Barrio Tres Estrellas y Barrio Sarmiento alto\n• Barrio Piedrabuena",
            "Godoy Cruz es el departamento más demandado por cercanía a Capital. Priorizar el eje centro, Trapiche y Bombal. Descartar cualquier propiedad al oeste del corredor del Parque San Vicente hacia el pedemonte si no es barrio cerrado.",
        ),
        (
            "Luján de Cuyo",
            "• Carrodilla Centro y Oeste (rápido acceso por Acceso Sur/San Martín)\n• Mayor Drummond (ambiente de pueblo residencial y viñedos)\n• Vistalba y Chacras de Coria (microclima, categoría)\n• La Puntilla y Luján Centro",
            "• Cuadro Estación y Perdriel periférico\n• Asentamientos ribereños contra el Río Mendoza\n• Franjas este de Carrodilla cercanas al zanjón/límite Maipú",
            "Excelente relación precio/terreno. En Luján por USD 100k-140k se consiguen terrenos más grandes (200-400 m²) que en Godoy Cruz.",
        ),
        (
            "Maipú",
            "• Luzuriaga (Bº Ferroviario, Bº González Galiño): muy seguro y con Metrotranvía directo a Capital\n• Zona El Torreón / Gabrielli / Sarmiento: polo moderno y barrios cerrados\n• Gutiérrez residencial consolidado\n• Maipú Centro y Parque Metropolitano",
            "• Barrio Renacer\n• Barrio Soberanía Nacional\n• Asentamientos sobre vías de Gutiérrez\n• Barrio Triple / San Roque zonas bajas",
            "Luzuriaga es la opción con mejor conectividad gracias al Metrotranvía. El Torreón ofrece el entorno más moderno y seguro para familias.",
        ),
        (
            "Cuarta Sección / Capital",
            "• Cuarta Sección Oeste (entre Av. San Martín y Parque Central / Boulogne Sur Mer)\n• Entorno Parque Central y Nave Cultural\n• Ejes de calles San Martín, España y 9 de Julio",
            "• Cuarta Sección Este (hacia Costanera y Canal Cacique Guaymallén, insegura de noche)\n• Zonas periféricas: Bº San Martín, Bº Olivares, Bº Flores (cerca UNCUYO)",
            "En la Cuarta Sección la regla de oro es estar del lado OESTE de Av. San Martín. Cuanto más cerca del Parque Central, mayor plusvalía y seguridad.",
        ),
    ]

    for row_idx, (d, rec, evi, tips) in enumerate(guide_rows, 4):
        ws3.row_dimensions[row_idx].height = 110
        fill_g = zebra_fill if row_idx % 2 == 0 else PatternFill(fill_type=None)

        cells = [
            ws3.cell(row=row_idx, column=1, value=d),
            ws3.cell(row=row_idx, column=2, value=rec),
            ws3.cell(row=row_idx, column=3, value=evi),
            ws3.cell(row=row_idx, column=4, value=tips),
        ]
        cells[0].font = bold_font
        cells[0].alignment = Alignment(horizontal="center", vertical="center")
        cells[1].alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        cells[2].alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        cells[3].alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

        for c in cells:
            c.border = border_thin
            if fill_g.fill_type:
                c.fill = fill_g

    guide_widths = {"A": 22, "B": 45, "C": 45, "D": 50}
    for col_letter, width in guide_widths.items():
        ws3.column_dimensions[col_letter].width = width

    output_path = os.path.abspath("casas_mendoza_recomendadas.xlsx")
    wb.save(output_path)
    print(f"\n[EXITO] Archivo Excel guardado en: {output_path}")
    print(f"        Total casas incluidas: {len(unicos)}")


if __name__ == "__main__":
    main()
