"""
pipeline_mendoza_pro.py

Pipeline integral de búsqueda, filtrado riguroso, enriquecimiento de datos y
generación de informe profesional en Excel para casas en Mendoza (Godoy Cruz,
Luján de Cuyo, Maipú y Cuarta Sección / Capital) con presupuesto <= PRECIO_MAX_USD (ahorro del 25% para el crédito BNA).

Fuentes:
- InMoup (todas las subzonas residenciales)
- Zonaprop (13 subzonas clave x 2 páginas)
- MercadoLibre Inmuebles (4 departamentos x 2 páginas)
- Argenprop (3 departamentos x 2 páginas; tiene antibot, puede traer menos)
- Más Hogares con BNA (API JSON del catálogo hipotecario del Banco Nación)

Filtros:
- Exclusión total de villas y zonas rojas (Villa Hipódromo, Campo Pappa, La Gloria, etc.)
- Exclusión de avisos falsos / alquileres (< USD 20.000)
- Presupuesto máximo: PRECIO_MAX_USD = AHORRO_USD / 25% (el BNA financia hasta el 75%)
"""

import os
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from smartwebsearch.http import PoliteSession
from smartwebsearch.sources.inmoup import (
    _is_zona_excluida,
    _normalize_str,
    scrape_zona as scrape_inmoup_zona,
)

# Presupuesto: el BNA financia hasta el 75% del valor de compra o tasación (el menor),
# así que el ahorro tiene que cubrir el 25% restante.
AHORRO_USD = 20_000
PORCENTAJE_FINANCIADO_BNA = 0.75
PRECIO_MAX_USD = round(AHORRO_USD / (1 - PORCENTAJE_FINANCIADO_BNA))  # 80.000
PRECIO_MAX_TXT = f"USD {PRECIO_MAX_USD:,}".replace(",", ".")

# Forzar UTF-8 en consola de Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


@dataclass
class CasaPro:
    id_unico: str
    portal: str
    departamento: str
    barrio_especifico: str
    tipo_urbanizacion: str     # Barrio Privado/Cerrado, Residencial Premium, Residencial Consolidado, Urbano Céntrico
    condicion: str             # A Estrenar / Reciclada, Muy Buen Estado, A Reciclar
    precio_usd: float
    m2_cubiertos: Optional[float]
    m2_terreno: Optional[float]
    precio_m2_cubierto: Optional[float]
    precio_m2_terreno: Optional[float]
    dormitorios: Optional[int]
    banos: Optional[int]
    cocheras: Optional[int]
    score_oportunidad: str     # ★★★★★, ★★★★☆, etc.
    titulo: str
    direccion: str
    url: str
    justificacion_zona: str
    expensas_ars: Optional[float] = None  # mensuales; solo cuando el aviso las publica


def classify_departamento(texto: str, default_dept: str = "") -> str:
    t = _normalize_str(texto)
    if any(k in t for k in ["cuarta seccion", "4ta seccion", "parque central", "sexta seccion", "quinta seccion", "mendoza capital", "capital"]):
        return "Cuarta Sección / Capital"
    if any(k in t for k in ["godoy cruz", "bombal", "trapiche", "fuchs", "bancario", "benegas", "san vicente"]):
        return "Godoy Cruz"
    if any(k in t for k in ["lujan", "carrodilla", "drummond", "vistalba", "chacras", "puntilla"]):
        return "Luján de Cuyo"
    if any(k in t for k in ["maipu", "luzuriaga", "gutierrez", "torreon", "terrada"]):
        return "Maipú"
    return default_dept or "Gran Mendoza"


def classify_barrio_detallado(texto: str, dept: str) -> tuple[str, str, str]:
    """
    Devuelve: (barrio_especifico, tipo_urbanizacion, justificacion)
    """
    t = _normalize_str(texto)

    # Detección de barrio privado / cerrado transversal
    es_privado = bool(re.search(r"barrio\s+privado|barrio\s+cerrado|club\s+de\s+campo|country|seguridad\s+24|portal\s+de\s+benegas|el\s+torreon", t))

    if dept == "Godoy Cruz":
        if "bombal" in t:
            return "Bombal Sur", "Residencial Premium", "Zona más cotizada de Godoy Cruz, alta seguridad, arbolada y pegada a Capital."
        if "trapiche" in t:
            return "Barrio Trapiche", "Residencial Consolidado", "Barrio muy familiar y seguro, junto a Parque Benegas y ciclovía principal."
        if "benegas" in t or "portal de benegas" in t or "parque gobernador benegas" in t:
            tipo = "Barrio Privado/Cerrado" if es_privado else "Residencial Consolidado"
            return "Gobernador Benegas", tipo, "Excelente ubicación sobre San Martín Sur, ciclovía, cercano a Palmares Open Mall."
        if "fuchs" in t:
            return "Barrio Fuchs", "Residencial Consolidado", "Tradicional barrio residencial con centro comercial propio, escuelas y alta tranquilidad."
        if "bancario" in t:
            return "Barrio Bancario", "Residencial Consolidado", "Ambiente tranquilo, residencial homogéneo y excelente acceso a transporte."
        if "villa marini" in t or "marini" in t:
            return "Villa Marini / Casino", "Residencial Consolidado", "Zona céntrica de casas bajas, segura, próxima al polo comercial del Casino y ciclovía."
        if "san vicente" in t or "plaza godoy cruz" in t or "centro" in t:
            return "Godoy Cruz Centro / San Vicente", "Urbano Céntrico", "Corazón cívico de Godoy Cruz con patrullaje constante y todos los servicios."
        if es_privado:
            return "Godoy Cruz Bo Privado", "Barrio Privado/Cerrado", "Urbanización cerrada con control de ingreso y seguridad privada."
        return "Godoy Cruz Residencial", "Residencial Consolidado", "Sector residencial seguro verificado, fuera de zonas de conflicto."

    elif dept == "Luján de Cuyo":
        if "chacras" in t:
            return "Chacras de Coria", "Residencial Premium", "Zona de máxima categoría, microclima excepcional, arbolado y polos gastronómicos."
        if "vistalba" in t:
            tipo = "Barrio Privado/Cerrado" if es_privado else "Residencial Premium"
            return "Vistalba", tipo, "Entorno campestre arbolado, vistas a la cordillera y urbanizaciones residenciales seguras."
        if "carrodilla" in t:
            tipo = "Barrio Privado/Cerrado" if es_privado else "Residencial Consolidado"
            return "Carrodilla Centro / Residencial", tipo, "Conectividad inmediata a Godoy Cruz y Capital por Acceso Sur o San Martín."
        if "drummond" in t:
            return "Mayor Drummond", "Residencial Consolidado", "Barrio tranquilo rodeado de bodegas y viñedos, con ambiente residencial sereno."
        if "puntilla" in t:
            return "La Puntilla", "Residencial Premium", "Inmediaciones de Palmares Open Mall y Corredor del Oeste, zona de alto valor."
        if "centro" in t or "saenz pena" in t or "plaza" in t:
            return "Luján Centro", "Urbano Céntrico", "Sector céntrico histórico con bancos, comercios y transporte directo."
        if es_privado:
            return "Luján Bo Privado", "Barrio Privado/Cerrado", "Loteo cerrado o barrio privado con seguridad en Luján de Cuyo."
        return "Luján Residencial", "Residencial Consolidado", "Propiedades de terreno generoso en sectores tranquilos de Luján."

    elif dept == "Maipú":
        if "torreon" in t:
            return "El Torreón / Urquiza", "Barrio Privado/Cerrado", "Uno de los desarrollos más modernos y seguros de Gran Mendoza (club, colegio, comercios)."
        if "luzuriaga" in t or "cardenal" in t or "gonzalez galino" in t:
            return "Luzuriaga Residencial", "Residencial Consolidado", "Zona altamente valorada por el paso del Metrotranvía y rápida conexión a Capital."
        if "ferroviario" in t:
            return "Barrio Ferroviario (Luzuriaga)", "Residencial Consolidado", "Barrio cerrado y organizado, muy seguro y familiar."
        if "gutierrez" in t:
            return "Gutiérrez Residencial", "Residencial Consolidado", "Sector tradicional con comercios, escuelas y ambiente de barrio seguro."
        if "terrada" in t or "ayres de terrada" in t:
            return "Terrada / Barrios Privados", "Barrio Privado/Cerrado", "Corredor residencial de loteos cerrados y barrios privados familiares."
        if "irigoyen" in t or "rivadavia" in t or "centro" in t or "parque metropolitano" in t:
            return "Maipú Centro / Parque", "Urbano Céntrico", "Zona céntrica junto a la Plaza Principal y el Parque Metropolitano de Maipú."
        if es_privado:
            return "Maipú Bo Privado", "Barrio Privado/Cerrado", "Barrio privado con seguridad 24 horas y amenidades."
        return "Maipú Residencial", "Residencial Consolidado", "Sector residencial de Maipú consolidado y seguro."

    else:  # Cuarta Sección / Capital
        if "cuarta oeste" in t or "4ta oeste" in t or "parque central" in t:
            return "Cuarta Sección Oeste (Parque Central)", "Residencial Consolidado", "La mejor zona de la 4ta: entre San Martín y Parque Central, residencial, tranquila y cultural."
        if "quinta" in t or "5ta" in t:
            return "Quinta Sección", "Residencial Premium", "Barrio más cotizado y tradicional de la Ciudad de Mendoza, pegado al Parque San Martín."
        if "sexta" in t or "6ta" in t:
            return "Sexta Sección", "Residencial Consolidado", "Barrio residencial arbolado, tranquilo y de casas bajas en Capital."
        if "cuarta" in t or "4ta" in t:
            return "Cuarta Sección", "Residencial Consolidado", "Barrio céntrico tradicional con excelente conectividad, escuelas y comercios."
        if "lavalle" in t or "olascoaga" in t or "roca" in t or "capital" in t or "centro" in t:
            return "Capital Residencial / Centro", "Urbano Céntrico", "Ubicación céntrica con seguridad urbana, servicios y conectividad total."
        return "Capital Residencial", "Residencial Consolidado", "Zona residencial urbana en Ciudad de Mendoza."


def detect_condicion(texto: str) -> str:
    t = _normalize_str(texto)
    if re.search(r"a\s+reciclar|a\s+demoler|para\s+reciclar|reciclar|refaccionar", t):
        return "A Reciclar / Inversión"
    if re.search(r"a\s+estrenar|estrenar|a\s+nuevo|reciclad[ao]\s+a\s+nuevo|impecable|excelente\s+estado", t):
        return "A Estrenar / Reciclada"
    return "Muy Buen Estado"


def extract_features_from_text(text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Devuelve (dormitorios, banos, cocheras)."""
    m_dorm = re.search(r"(\d+)\s*(?:dorm|habitaci|dormitorio)", text, re.I)
    m_ban = re.search(r"(\d+)\s*baño", text, re.I)
    m_coch = re.search(r"(\d+)\s*(?:coch|cochera|garage|auto)", text, re.I)

    dorm = int(m_dorm.group(1)) if m_dorm and int(m_dorm.group(1)) <= 10 else None
    ban = int(m_ban.group(1)) if m_ban and int(m_ban.group(1)) <= 8 else None
    coch = int(m_coch.group(1)) if m_coch and int(m_coch.group(1)) <= 6 else None
    return dorm, ban, coch


def calculate_opportunity_score(precio_m2_cub: Optional[float], tipo_urb: str, condicion: str) -> str:
    if condicion == "A Reciclar / Inversión":
        return "★★★☆☆ Oportunidad Reforma"

    if not precio_m2_cub:
        if tipo_urb in ["Barrio Privado/Cerrado", "Residencial Premium"]:
            return "★★★★☆ Destacada"
        return "★★★☆☆ Mercado"

    if precio_m2_cub < 480:
        return "★★★★★ Oportunidad Top"
    elif precio_m2_cub < 650:
        return "★★★★☆ Excelente Valor"
    elif precio_m2_cub < 850:
        return "★★★☆☆ Precio de Mercado"
    elif tipo_urb in ["Barrio Privado/Cerrado", "Residencial Premium"]:
        return "★★★☆☆ Premium Justificado"
    else:
        return "★★☆☆☆ Rango Superior"


# ─── Scrapers ──────────────────────────────────────────────────────────────────

def harvest_zonaprop() -> list[CasaPro]:
    zonaprop_configs = [
        ("Godoy Cruz", f"casas-venta-godoy-cruz-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Godoy Cruz", f"casas-venta-gobernador-benegas-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Godoy Cruz", f"casas-venta-bombal-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Luján de Cuyo", f"casas-venta-lujan-de-cuyo-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Luján de Cuyo", f"casas-venta-carrodilla-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Luján de Cuyo", f"casas-venta-mayor-drummond-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Luján de Cuyo", f"casas-venta-chacras-de-coria-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Luján de Cuyo", f"casas-venta-vistalba-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Maipú", f"casas-venta-maipu-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Maipú", f"casas-venta-luzuriaga-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Maipú", f"casas-venta-gutierrez-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Cuarta Sección / Capital", f"casas-venta-cuarta-seccion-hasta-{PRECIO_MAX_USD}-dolar"),
        ("Cuarta Sección / Capital", f"casas-venta-mendoza-capital-hasta-{PRECIO_MAX_USD}-dolar"),
    ]

    session = PoliteSession()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
    }

    items: list[CasaPro] = []
    vistos = set()

    for dept_default, slug in zonaprop_configs:
        for page in [1, 2]:
            url = f"https://www.zonaprop.com.ar/{slug}.html" if page == 1 else f"https://www.zonaprop.com.ar/{slug}-pagina-{page}.html"
            try:
                resp = session.get(url, headers=headers, timeout=12)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                postings = soup.find_all(attrs={"data-qa": "posting PROPERTY"})

                for p in postings:
                    href = p.get("data-to-posting", "")
                    if not href:
                        a_tag = p.find("a", href=True)
                        if a_tag:
                            href = a_tag["href"]
                    clean_url = ("https://www.zonaprop.com.ar" + href.split("?")[0]) if href else ""
                    if not clean_url or clean_url in vistos:
                        continue

                    # Precio
                    price_tag = p.find(attrs={"data-qa": "POSTING_CARD_PRICE"})
                    price_txt = price_tag.get_text(strip=True) if price_tag else ""
                    m_p = re.search(r"USD\s*([\d\.]+)", price_txt)
                    if not m_p:
                        continue
                    precio = float(m_p.group(1).replace(".", ""))
                    if precio > PRECIO_MAX_USD or precio < 20_000:
                        continue

                    # Textos
                    loc_tag = p.find(attrs={"data-qa": "POSTING_CARD_LOCATION"})
                    loc = loc_tag.get_text(" ", strip=True) if loc_tag else ""
                    desc_tag = p.find(attrs={"data-qa": "POSTING_CARD_DESCRIPTION"})
                    desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""
                    title_tag = p.find(attrs={"data-qa": "POSTING_CARD_TITLE"})
                    title = title_tag.get_text(" ", strip=True) if title_tag else desc[:80]
                    texto_completo = f"{title} {loc} {desc}"

                    # Filtro de seguridad
                    excl, raz = _is_zona_excluida(texto_completo)
                    if excl:
                        continue

                    # Features
                    feat_tag = p.find(attrs={"data-qa": "POSTING_CARD_FEATURES"})
                    ftxt = feat_tag.get_text(" | ", strip=True) if feat_tag else ""
                    combined_info = f"{ftxt} | {desc}"

                    # m²
                    m_cub = re.search(r"(\d+)\s*m²\s*cub", ftxt)
                    m_tot = re.search(r"(\d+)\s*m²\s*tot", ftxt)
                    cub = float(m_cub.group(1)) if m_cub else None
                    tot = float(m_tot.group(1)) if m_tot else None

                    # Respaldo de m² cubiertos desde la descripción
                    if not cub:
                        m_cub_desc = re.search(r"(\d{2,4})\s*m[²2]?\s*(?:cubiertos|cubierta|construidos|cub)", desc, re.I)
                        if not m_cub_desc:
                            m_cub_desc = re.search(r"superficie\s+cubierta\s*(?:total)?\s*(?:de)?\s*(\d{2,4})", desc, re.I)
                        if m_cub_desc:
                            val = float(m_cub_desc.group(1))
                            if 30 <= val <= 1000:
                                cub = val

                    # Respaldo de m² terreno desde la descripción
                    if not tot:
                        m_tot_desc = re.search(r"(\d{2,4})\s*m[²2]?\s*(?:de\s+terreno|totales|total)", desc, re.I)
                        if m_tot_desc:
                            val = float(m_tot_desc.group(1))
                            if 50 <= val <= 2500:
                                tot = val

                    # Garantizar coherencia
                    if cub and tot and cub > tot:
                        cub, tot = tot, cub

                    # Dormitorios, baños, cocheras
                    dorm, ban, coch = extract_features_from_text(combined_info)

                    # Clasificación
                    dept = classify_departamento(texto_completo, default_dept=dept_default)
                    barrio, tipo_urb, justif = classify_barrio_detallado(texto_completo, dept)
                    condicion = detect_condicion(texto_completo)

                    p_cub = round(precio / cub, 0) if cub and cub > 15 else None
                    p_tot = round(precio / tot, 0) if tot and tot > 20 else None

                    score = calculate_opportunity_score(p_cub, tipo_urb, condicion)

                    vistos.add(clean_url)
                    items.append(CasaPro(
                        id_unico=f"ZP-{len(items)+1}",
                        portal="Zonaprop",
                        departamento=dept,
                        barrio_especifico=barrio,
                        tipo_urbanizacion=tipo_urb,
                        condicion=condicion,
                        precio_usd=precio,
                        m2_cubiertos=cub,
                        m2_terreno=tot,
                        precio_m2_cubierto=p_cub,
                        precio_m2_terreno=p_tot,
                        dormitorios=dorm,
                        banos=ban,
                        cocheras=coch,
                        score_oportunidad=score,
                        titulo=title[:110],
                        direccion=loc,
                        url=clean_url,
                        justificacion_zona=justif,
                    ))
            except Exception as e:
                print(f"[Zonaprop] Error en {slug} p.{page}: {e}")

    return items


def harvest_inmoup() -> list[CasaPro]:
    subzonas = [
        ("casas-en-venta-en-godoy-cruz", "Godoy Cruz"),
        ("casas-en-venta-en-bombal", "Godoy Cruz"),
        ("casas-en-venta-en-carrodilla", "Luján de Cuyo"),
        ("casas-en-venta-en-mayor-drummond", "Luján de Cuyo"),
        ("casas-en-venta-en-chacras-de-coria", "Luján de Cuyo"),
        ("casas-en-venta-en-vistalba", "Luján de Cuyo"),
        ("casas-en-venta-en-lujan-de-cuyo", "Luján de Cuyo"),
        ("casas-en-venta-en-maipu", "Maipú"),
        ("casas-en-venta-en-luzuriaga", "Maipú"),
        ("casas-en-venta-en-gutierrez", "Maipú"),
        ("casas-en-venta-en-cuarta-seccion", "Cuarta Sección / Capital"),
        ("casas-en-venta-en-mendoza", "Cuarta Sección / Capital"),
    ]

    session = PoliteSession()
    items: list[CasaPro] = []
    vistos = set()

    for slug, dept_default in subzonas:
        try:
            props = scrape_inmoup_zona(slug, session=session, max_precio_usd=PRECIO_MAX_USD)
            for p in props:
                if p.excluida or not p.precio_usd or p.precio_usd < 20_000 or p.precio_usd > PRECIO_MAX_USD:
                    continue
                if p.url and p.url in vistos:
                    continue

                texto_completo = f"{p.titulo} {p.ubicacion} {p.descripcion}"
                dept = classify_departamento(texto_completo, default_dept=dept_default)
                barrio, tipo_urb, justif = classify_barrio_detallado(texto_completo, dept)
                condicion = detect_condicion(texto_completo)
                dorm, ban, coch = extract_features_from_text(texto_completo)

                cub = p.m2_cubiertos
                tot = p.m2_totales
                if cub and tot and cub > tot:
                    cub, tot = tot, cub

                p_cub = round(p.precio_usd / cub, 0) if cub and cub > 15 else None
                p_tot = round(p.precio_usd / tot, 0) if tot and tot > 20 else None
                score = calculate_opportunity_score(p_cub, tipo_urb, condicion)

                if p.url:
                    vistos.add(p.url)

                items.append(CasaPro(
                    id_unico=f"INM-{len(items)+1}",
                    portal="InMoup",
                    departamento=dept,
                    barrio_especifico=barrio,
                    tipo_urbanizacion=tipo_urb,
                    condicion=condicion,
                    precio_usd=p.precio_usd,
                    m2_cubiertos=cub,
                    m2_terreno=tot,
                    precio_m2_cubierto=p_cub,
                    precio_m2_terreno=p_tot,
                    dormitorios=dorm,
                    banos=ban,
                    cocheras=coch,
                    score_oportunidad=score,
                    titulo=p.titulo[:110],
                    direccion=p.ubicacion,
                    url=p.url,
                    justificacion_zona=justif,
                ))
        except Exception as e:
            print(f"[InMoup] Error en {slug}: {e}")

    return items


# ─── Generador Excel ───────────────────────────────────────────────────────────

def build_excel_workbook(casas: list[CasaPro], output_file: str):
    wb = openpyxl.Workbook()

    # Paleta de colores ejecutiva
    c_navy = "1B365D"       # Azul marino encabezado
    c_gold = "C59B27"       # Dorado de oportunidad
    c_ice_blue = "EDF2F7"   # Fondo alternado
    c_white = "FFFFFF"
    c_border = "D0D5DD"

    fill_header = PatternFill(start_color=c_navy, end_color=c_navy, fill_type="solid")
    fill_zebra = PatternFill(start_color=c_ice_blue, end_color=c_ice_blue, fill_type="solid")
    fill_top = PatternFill(start_color="E6FFFA", end_color="E6FFFA", fill_type="solid")     # Verde menta suave
    fill_privado = PatternFill(start_color="FEFCBF", end_color="FEFCBF", fill_type="solid") # Amarillo suave

    font_header = Font(name="Segoe UI", size=10, bold=True, color=c_white)
    font_bold = Font(name="Segoe UI", size=9, bold=True)
    font_normal = Font(name="Segoe UI", size=9)
    font_link = Font(name="Segoe UI", size=9, color="0055CC", underline="single")
    font_score = Font(name="Segoe UI", size=9, bold=True, color="975A16")

    border_cell = Border(
        left=Side(style="thin", color=c_border),
        right=Side(style="thin", color=c_border),
        top=Side(style="thin", color=c_border),
        bottom=Side(style="thin", color=c_border),
    )

    def write_table_headers(ws, row_idx: int, col_names: list[str]):
        ws.row_dimensions[row_idx].height = 26
        for col_i, name in enumerate(col_names, 1):
            cell = ws.cell(row=row_idx, column=col_i, value=name)
            cell.fill = fill_header
            cell.font = font_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border_cell

    def write_casa_row(ws, r_idx: int, seq_num: int, c: CasaPro, highlight_fill=None):
        ws.row_dimensions[r_idx].height = 20
        fill = highlight_fill if highlight_fill else (fill_zebra if r_idx % 2 == 0 else PatternFill(fill_type=None))

        cells = [
            (1, seq_num, Alignment(horizontal="center", vertical="center"), None, None),
            (2, c.departamento, Alignment(horizontal="left", vertical="center"), font_bold, None),
            (3, c.barrio_especifico, Alignment(horizontal="left", vertical="center"), font_normal, None),
            (4, c.tipo_urbanizacion, Alignment(horizontal="center", vertical="center"), font_normal, None),
            (5, c.condicion, Alignment(horizontal="center", vertical="center"), font_normal, None),
            (6, c.precio_usd, Alignment(horizontal="right", vertical="center"), font_bold, '"USD "#,##0'),
            (7, c.m2_cubiertos or "—", Alignment(horizontal="right", vertical="center"), font_normal, '#,##0" m²"' if c.m2_cubiertos else None),
            (8, c.m2_terreno or "—", Alignment(horizontal="right", vertical="center"), font_normal, '#,##0" m²"' if c.m2_terreno else None),
            (9, c.precio_m2_cubierto or "—", Alignment(horizontal="right", vertical="center"), font_bold, '"USD "#,##0"/m²"' if c.precio_m2_cubierto else None),
            (10, c.precio_m2_terreno or "—", Alignment(horizontal="right", vertical="center"), font_normal, '"USD "#,##0"/m²"' if c.precio_m2_terreno else None),
            (11, f"{c.dormitorios} d" if c.dormitorios else "—", Alignment(horizontal="center", vertical="center"), font_normal, None),
            (12, f"{c.banos} b" if c.banos else "—", Alignment(horizontal="center", vertical="center"), font_normal, None),
            (13, f"{c.cocheras} c" if c.cocheras else "—", Alignment(horizontal="center", vertical="center"), font_normal, None),
            (14, c.score_oportunidad, Alignment(horizontal="center", vertical="center"), font_score, None),
            (15, c.titulo, Alignment(horizontal="left", vertical="center"), font_normal, None),
            (16, c.justificacion_zona, Alignment(horizontal="left", vertical="center"), font_normal, None),
            (17, c.portal, Alignment(horizontal="center", vertical="center"), font_normal, None),
        ]

        for col_i, val, align, f_font, num_fmt in cells:
            cell = ws.cell(row=r_idx, column=col_i, value=val)
            cell.alignment = align
            cell.font = f_font or font_normal
            cell.border = border_cell
            if fill.fill_type:
                cell.fill = fill
            if num_fmt:
                cell.number_format = num_fmt

        # Columna 18: Link clickeable
        c_link = ws.cell(row=r_idx, column=18)
        if c.url:
            c_link.value = f"Ver en {c.portal}"
            c_link.hyperlink = c.url
            c_link.font = font_link
        else:
            c_link.value = "—"
            c_link.font = font_normal
        c_link.alignment = Alignment(horizontal="center", vertical="center")
        c_link.border = border_cell
        if fill.fill_type:
            c_link.fill = fill

        # Columna 19: expensas mensuales (costo fijo a sumar en barrios privados)
        c_exp = ws.cell(row=r_idx, column=19, value=c.expensas_ars or "—")
        c_exp.number_format = '"$ "#,##0' if c.expensas_ars else "General"
        c_exp.alignment = Alignment(horizontal="right", vertical="center")
        c_exp.font = font_normal
        c_exp.border = border_cell
        if fill.fill_type:
            c_exp.fill = fill

    standard_headers = [
        "#",
        "Departamento",
        "Barrio / Zona",
        "Tipo Urbanización",
        "Condición",
        "Precio (USD)",
        "M² Cubiertos",
        "M² Terreno",
        "USD / M² Cub",
        "USD / M² Terr",
        "Dorm.",
        "Baños",
        "Coch.",
        "Score Oportunidad",
        "Título / Anuncio",
        "Por qué se recomienda",
        "Portal",
        "Enlace Directo",
        "Expensas ($/mes)",
    ]

    col_widths = {
        "A": 5, "B": 22, "C": 26, "D": 22, "E": 20, "F": 15, "G": 13, "H": 13,
        "I": 15, "J": 14, "K": 8, "L": 8, "M": 8, "N": 20, "O": 42, "P": 45,
        "Q": 13, "R": 22, "S": 15
    }

    # ── Hoja 1: TOP 25 Oportunidades ───────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Top 25 Oportunidades"
    ws1.merge_cells("A1:S1")
    t1 = ws1["A1"]
    t1.value = f"TOP 25 OPORTUNIDADES — MEJOR RELACIÓN PRECIO/M² EN ZONAS SEGURAS (≤ {PRECIO_MAX_TXT})"
    t1.font = Font(name="Segoe UI", size=13, bold=True, color=c_navy)
    ws1.row_dimensions[1].height = 26

    ws1.merge_cells("A2:S2")
    sub1 = ws1["A2"]
    sub1.value = "Selección de las casas con el menor costo por m² cubierto en barrios residenciales y privados sin riesgo de seguridad."
    sub1.font = Font(name="Segoe UI", size=9, italic=True, color="555555")
    ws1.row_dimensions[2].height = 18

    write_table_headers(ws1, 4, standard_headers)

    # Filtrar candidatas para el top: que tengan m² cubierto y no sean a demoler
    candidatas_top = [c for c in casas if c.precio_m2_cubierto and c.condicion != "A Reciclar / Inversión"]
    candidatas_top.sort(key=lambda x: (x.precio_m2_cubierto, x.precio_usd))
    top_25 = candidatas_top[:25]

    for i, c in enumerate(top_25, 5):
        write_casa_row(ws1, i, i - 4, c, highlight_fill=fill_top if i % 2 == 0 else None)

    ws1.auto_filter.ref = f"A4:S{len(top_25)+4}"
    ws1.freeze_panes = "C5"  # encabezado y departamento siempre visibles
    for col, w in col_widths.items():
        ws1.column_dimensions[col].width = w

    # ── Hoja 2: Barrios Privados y Cerrados ────────────────────────────────────
    ws2 = wb.create_sheet(title="Barrios Privados y Cerrados")
    ws2.merge_cells("A1:S1")
    t2 = ws2["A1"]
    t2.value = f"CASAS EN BARRIOS PRIVADOS Y URBANIZACIONES CERRADAS (≤ {PRECIO_MAX_TXT})"
    t2.font = Font(name="Segoe UI", size=13, bold=True, color=c_navy)
    ws2.row_dimensions[1].height = 26

    ws2.merge_cells("A2:S2")
    sub2 = ws2["A2"]
    sub2.value = "Propiedades con control de acceso, seguridad 24hs o perímetro cerrado en Luján de Cuyo, Maipú y Godoy Cruz."
    sub2.font = Font(name="Segoe UI", size=9, italic=True, color="555555")
    ws2.row_dimensions[2].height = 18

    write_table_headers(ws2, 4, standard_headers)

    privados = [c for c in casas if c.tipo_urbanizacion == "Barrio Privado/Cerrado"]
    privados.sort(key=lambda x: (x.precio_m2_cubierto or 9999, x.precio_usd))

    for i, c in enumerate(privados, 5):
        write_casa_row(ws2, i, i - 4, c, highlight_fill=fill_privado if i % 2 == 0 else None)

    ws2.auto_filter.ref = f"A4:S{len(privados)+4}"
    ws2.freeze_panes = "C5"  # encabezado y departamento siempre visibles
    for col, w in col_widths.items():
        ws2.column_dimensions[col].width = w

    # ── Hoja 3: Todas las Casas Recomendadas ────────────────────────────────────
    ws3 = wb.create_sheet(title="Todas las Casas")
    ws3.merge_cells("A1:S1")
    t3 = ws3["A1"]
    t3.value = f"CATÁLOGO COMPLETO DE CASAS EN ZONAS RECOMENDADAS ({len(casas)} PROPIEDADES)"
    t3.font = Font(name="Segoe UI", size=13, bold=True, color=c_navy)
    ws3.row_dimensions[1].height = 26

    ws3.merge_cells("A2:S2")
    sub3 = ws3["A2"]
    sub3.value = f"Filtro anti-villas activo | Publicaciones deduplicadas de InMoup, Zonaprop, MercadoLibre, Argenprop y BNA +Hogares | Presupuesto: hasta {PRECIO_MAX_TXT}"
    sub3.font = Font(name="Segoe UI", size=9, italic=True, color="555555")
    ws3.row_dimensions[2].height = 18

    write_table_headers(ws3, 4, standard_headers)

    dept_order = {"Godoy Cruz": 1, "Luján de Cuyo": 2, "Maipú": 3, "Cuarta Sección / Capital": 4}
    casas_ordenadas = sorted(casas, key=lambda x: (dept_order.get(x.departamento, 99), x.precio_m2_cubierto or 9999, x.precio_usd))

    for i, c in enumerate(casas_ordenadas, 5):
        write_casa_row(ws3, i, i - 4, c)

    ws3.auto_filter.ref = f"A4:S{len(casas)+4}"
    ws3.freeze_panes = "C5"  # encabezado y departamento siempre visibles
    for col, w in col_widths.items():
        ws3.column_dimensions[col].width = w

    # ── Hoja 4: Resumen Estadístico y Métricas por Zona ────────────────────────
    ws4 = wb.create_sheet(title="Resumen y Tasación M2")
    ws4.merge_cells("A1:H1")
    t4 = ws4["A1"]
    t4.value = "ESTADÍSTICAS COMPARATIVAS DE PRECIO Y VALOR POR M² POR DEPARTAMENTO"
    t4.font = Font(name="Segoe UI", size=13, bold=True, color=c_navy)
    ws4.row_dimensions[1].height = 26

    sum_headers = [
        "Departamento",
        "Total Casas",
        "Precio Mínimo",
        "Precio Mediana",
        "Precio Máximo",
        "Mediana USD/M² Cubierto",
        "Mediana USD/M² Terreno",
        "Barrios Clave Recomendados",
    ]
    write_table_headers(ws4, 3, sum_headers)

    dept_highlights = {
        "Godoy Cruz": "Bombal Sur, Trapiche, Fuchs, Bancario, Villa Marini, Benegas",
        "Luján de Cuyo": "Carrodilla Centro, Mayor Drummond, Vistalba, Chacras, La Puntilla",
        "Maipú": "El Torreón, Luzuriaga (Metrotranvía), Bº Ferroviario, Gutiérrez, Terrada",
        "Cuarta Sección / Capital": "Cuarta Sección Oeste (Parque Central), Quinta Sección, Sexta Sección, Centro",
    }

    dept_groups = {}
    for c in casas:
        dept_groups.setdefault(c.departamento, []).append(c)

    r_s = 4
    for d_name in ["Godoy Cruz", "Luján de Cuyo", "Maipú", "Cuarta Sección / Capital"]:
        g = dept_groups.get(d_name, [])
        if not g:
            continue
        precios = [x.precio_usd for x in g if x.precio_usd]
        m2_cubs = [x.precio_m2_cubierto for x in g if x.precio_m2_cubierto]
        m2_tots = [x.precio_m2_terreno for x in g if x.precio_m2_terreno]

        row_vals = [
            d_name,
            len(g),
            min(precios) if precios else 0,
            statistics.median(precios) if precios else 0,
            max(precios) if precios else 0,
            statistics.median(m2_cubs) if m2_cubs else 0,
            statistics.median(m2_tots) if m2_tots else 0,
            dept_highlights.get(d_name, "Residencial"),
        ]

        ws4.row_dimensions[r_s].height = 22
        fill_row = fill_zebra if r_s % 2 == 0 else PatternFill(fill_type=None)
        for col_i, v in enumerate(row_vals, 1):
            cell = ws4.cell(row=r_s, column=col_i, value=v)
            cell.border = border_cell
            if fill_row.fill_type:
                cell.fill = fill_row
            if col_i in [3, 4, 5]:
                cell.number_format = '"USD "#,##0'
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.font = font_bold
            elif col_i in [6, 7]:
                cell.number_format = '"USD "#,##0"/m²"'
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.font = font_bold
            elif col_i == 2:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = font_bold
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")
                cell.font = font_bold if col_i == 1 else font_normal
        r_s += 1

    sum_widths = {"A": 25, "B": 14, "C": 18, "D": 18, "E": 18, "F": 24, "G": 24, "H": 55}
    for col, w in sum_widths.items():
        ws4.column_dimensions[col].width = w

    # ── Hoja 5: Guía de Seguridad y Barrios ────────────────────────────────────
    ws5 = wb.create_sheet(title="Guía de Seguridad y Barrios")
    ws5.merge_cells("A1:D1")
    t5 = ws5["A1"]
    t5.value = "GUÍA COMPLETA DE SEGURIDAD Y ELECCIÓN DE BARRIOS EN MENDOZA"
    t5.font = Font(name="Segoe UI", size=13, bold=True, color=c_navy)
    ws5.row_dimensions[1].height = 26

    g_headers = ["Departamento", "Zonas / Barrios Recomendados (Seguros)", "Zonas Rojas a Evitar (Villas / Riesgo)", "Estrategia para el Comprador"]
    write_table_headers(ws5, 3, g_headers)

    g_rows = [
        (
            "Godoy Cruz",
            "• Bombal Sur (categoría premium, arbolado, lindero a Capital)\n• Barrio Trapiche (entorno Parque Benegas y ciclovía)\n• Gobernador Benegas (sobre San Martín Sur, cerca de Palmares)\n• Barrio Fuchs (consolidado con centro comercial propio)\n• Barrio Bancario (residencial tradicional, muy pacífico)\n• Villa Marini y Centro cívico / San Vicente",
            "• Villa Hipódromo (calles Gorriti, Huarpes hacia el oeste y sur)\n• Campo Pappa y La Estanzuela alta (pedemonte oeste conflictivo)\n• Barrio La Gloria (sureste, sobre Acceso Sur, límite Maipú)\n• Barrio Tres Estrellas y Barrio Sarmiento alto\n• Barrio Piedrabuena",
            "Godoy Cruz es el departamento urbano más demandado por su cercanía al centro de Mendoza. Regla de oro: priorizar el cuadrante entre Av. San Martín Sur, ciclovía y límite con Capital. Descartar cualquier inmueble al oeste del Parque San Vicente que suba hacia el pedemonte.",
        ),
        (
            "Luján de Cuyo",
            "• Carrodilla Centro y Oeste (rápida salida a Acceso Sur y San Martín)\n• Mayor Drummond (ambiente de pueblo residencial, bodegas y tranquilidad)\n• Chacras de Coria y Vistalba (microclima, verde, categoría)\n• La Puntilla (estratégico junto a Palmares y Corredor del Oeste)\n• Luján Centro histórico (todos los servicios)",
            "• Cuadro Estación y Perdriel bajo\n• Asentamientos precarios ribereños del Río Mendoza\n• Franjas este de Carrodilla cercanas al zanjón/límite Maipú",
            "En Luján por USD 100k-140k el terreno suele duplicar o triplicar al de Godoy Cruz (lotes de 300 a 600 m²). Si buscas tranquilidad, verde y espacio para piscina o quincho, Carrodilla y Mayor Drummond son las mejores opciones.",
        ),
        (
            "Maipú",
            "• El Torreón (desarrollo modelo con club, colegio y seguridad)\n• Luzuriaga (máxima conectividad mediante el Metrotranvía hacia Capital)\n• Barrio Ferroviario (barrio cerrado, familiar y muy seguro)\n• Gutiérrez Residencial (tradicional, bodeguero y tranquilo)\n• Corredor Terrada (polo de barrios privados modernos)\n• Maipú Centro y Parque Metropolitano",
            "• Barrio Renacer\n• Barrio Soberanía Nacional\n• Asentamientos sobre vías de Gutiérrez\n• Barrio Triple y sectores vulnerables de San Roque",
            "Luzuriaga es la joya de Maipú para quien trabaja o estudia en Capital por el Metrotranvía. El Torreón y los barrios cerrados sobre Terrada ofrecen la mejor ecuación de seguridad y amenities dentro de este presupuesto.",
        ),
        (
            "Cuarta Sección / Capital",
            "• Cuarta Sección Oeste (entre Av. San Martín y Parque Central / Boulogne Sur Mer)\n• Entorno Parque Central y Nave Cultural\n• Ejes de calles San Martín, España y 9 de Julio\n• Quinta y Sexta Sección (en caso de encontrar oportunidades < 150k)",
            "• Cuarta Sección Este (al este de Av. San Martín hacia Costanera y Canal Cacique Guaymallén: zona oscura y peligrosa de noche)\n• Zonas limítrofes: Bº San Martín (Las Heras), Bº Olivares y Bº Flores (UNCUYO)",
            "En la Cuarta Sección la clave absoluta es la orientación: siempre buscar del lado OESTE de Av. San Martín. Cuanto más cerca del Parque Central, mayor calidad de vida, seguridad y revalorización inmobiliaria.",
        ),
    ]

    for r_i, (dep, rec, evi, tips) in enumerate(g_rows, 4):
        ws5.row_dimensions[r_i].height = 115
        fill_g = fill_zebra if r_i % 2 == 0 else PatternFill(fill_type=None)
        cells = [
            ws5.cell(row=r_i, column=1, value=dep),
            ws5.cell(row=r_i, column=2, value=rec),
            ws5.cell(row=r_i, column=3, value=evi),
            ws5.cell(row=r_i, column=4, value=tips),
        ]
        cells[0].font = font_bold
        cells[0].alignment = Alignment(horizontal="center", vertical="center")
        for c in cells[1:]:
            c.font = font_normal
            c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        for c in cells:
            c.border = border_cell
            if fill_g.fill_type:
                c.fill = fill_g

    g_widths = {"A": 22, "B": 48, "C": 48, "D": 52}
    for col, w in g_widths.items():
        ws5.column_dimensions[col].width = w

    output_path = os.path.abspath(output_file)
    wb.save(output_path)
    print(f"\n[OK] Excel profesional guardado exitosamente en:\n     {output_path}")
    print(f"     Total casas procesadas: {len(casas)}")
    print(f"     Top oportunidades: {len(top_25)}")
    print(f"     Barrios privados / cerrados: {len(privados)}")


DEPARTAMENTOS = ["Godoy Cruz", "Luján de Cuyo", "Maipú", "Cuarta Sección / Capital"]
_RE_EXPENSAS = re.compile(r"\$\s*([\d.]+)\s*expensas", re.I)


def _build_casa(portal: str, prefijo: str, n: int, dept_default: str, precio: float,
                titulo: str, ubicacion: str, features: str, url: str,
                expensas: Optional[float] = None, dept_fijo: bool = False) -> Optional[CasaPro]:
    """Aplica a un aviso los mismos filtros y clasificación que Zonaprop.
    None si está fuera de presupuesto o en una zona excluida."""
    if precio > PRECIO_MAX_USD or precio < 20_000:
        return None
    texto = f"{titulo} {ubicacion} {features}"
    if _is_zona_excluida(texto)[0]:
        return None
    m_cub = re.search(r"([\d.]+)\s*m²\s*cub", features)
    m_tot = re.search(r"([\d.]+)\s*m²\s*(?:tot|terr)", features)
    cub = float(m_cub.group(1).replace(".", "")) if m_cub else None
    tot = float(m_tot.group(1).replace(".", "")) if m_tot else None
    if cub and tot and cub > tot:
        cub, tot = tot, cub
    dorm, ban, coch = extract_features_from_text(f"{features} | {titulo}")
    # dept_fijo: el portal informa la localidad aparte, más confiable que adivinar por el texto
    # ("Carril Godoy Cruz, Guaymallén" no es Godoy Cruz).
    dept = dept_default if dept_fijo else classify_departamento(texto, default_dept=dept_default)
    barrio, tipo_urb, justif = classify_barrio_detallado(texto, dept)
    condicion = detect_condicion(texto)
    p_cub = round(precio / cub, 0) if cub and cub > 15 else None
    p_tot = round(precio / tot, 0) if tot and tot > 20 else None
    return CasaPro(
        id_unico=f"{prefijo}-{n}", portal=portal, departamento=dept,
        barrio_especifico=barrio, tipo_urbanizacion=tipo_urb, condicion=condicion,
        precio_usd=precio, m2_cubiertos=cub, m2_terreno=tot,
        precio_m2_cubierto=p_cub, precio_m2_terreno=p_tot,
        dormitorios=dorm, banos=ban, cocheras=coch,
        score_oportunidad=calculate_opportunity_score(p_cub, tipo_urb, condicion),
        titulo=titulo[:110], direccion=ubicacion, url=url, justificacion_zona=justif,
        expensas_ars=expensas,
    )


def harvest_mercadolibre() -> list[CasaPro]:
    """MercadoLibre Inmuebles: listado HTML con el tope de PRECIO_MAX_USD en la URL."""
    slugs = dict(zip(DEPARTAMENTOS, ["mendoza/godoy-cruz", "mendoza/lujan-de-cuyo",
                                     "mendoza/maipu", "mendoza-capital"]))
    session = PoliteSession()
    items: list[CasaPro] = []
    vistos = set()
    for dept, slug in slugs.items():
        for desde in (1, 49):  # 2 páginas de 48
            pag = "" if desde == 1 else f"_Desde_{desde}"
            url = f"https://inmuebles.mercadolibre.com.ar/casas/venta/{slug}/{pag}_PriceRange_0USD-{PRECIO_MAX_USD}USD_NoIndex_True"
            try:
                resp = session.get(url)
            except Exception as e:
                print(f"[mercadolibre] Error en {dept}: {e}")
                break
            if "account-verification" in resp.url:
                print("[mercadolibre] Bloqueado por verificación antibot; sigo con el resto.")
                return items
            cards = BeautifulSoup(resp.text, "html.parser").select("li.ui-search-layout__item")
            for card in cards:
                link = card.select_one("a.poly-component__title")
                price = card.select_one(".poly-price__current .andes-money-amount")
                if not link or not price or "dólares" not in (price.get("aria-label") or ""):
                    continue  # sin precio o en pesos
                m = re.search(r"(\d+)", price["aria-label"])
                url_aviso = link["href"].split("#")[0]
                if not m or url_aviso in vistos:
                    continue
                attrs = card.select_one(".poly-component__attributes-list")
                loc = card.select_one(".poly-component__location")
                casa = _build_casa(
                    "MercadoLibre", "ML", len(items) + 1, dept, float(m.group(1)),
                    link.get_text(" ", strip=True), loc.get_text(" ", strip=True) if loc else "",
                    attrs.get_text(" | ", strip=True) if attrs else "", url_aviso,
                )
                if casa:
                    vistos.add(url_aviso)
                    items.append(casa)
            if len(cards) < 48:
                break
    return items


def harvest_argenprop() -> list[CasaPro]:
    """Argenprop: listado HTML. Tiene antibot: tras unos pocos pedidos responde 202 vacío,
    así que va lento y, si lo bloquean, devuelve lo que juntó hasta ahí."""
    # ponytail: Capital no tiene slug verificado (el antibot cortó la prueba); se puede sumar después.
    slugs = {"Godoy Cruz": "godoy-cruz", "Luján de Cuyo": "lujan-de-cuyo", "Maipú": "maipu"}
    session = PoliteSession(delay=6)
    items: list[CasaPro] = []
    vistos = set()
    for dept, slug in slugs.items():
        for page in (1, 2):
            url = f"https://www.argenprop.com/casas/venta/{slug}/dolares-hasta-{PRECIO_MAX_USD}"
            if page > 1:
                url += f"?pagina-{page}"
            try:
                resp = session.get(url)
            except Exception as e:
                print(f"[argenprop] Error en {dept}: {e}")
                break
            cards = BeautifulSoup(resp.text, "html.parser").select(".listing__item a.card")
            if resp.status_code == 202 or not cards:
                print(f"[argenprop] Bloqueado por antibot en {dept} (página {page}); devuelvo lo juntado.")
                return items
            for card in cards:
                if card.get("idmoneda") != "2":  # 2 = dólares
                    continue
                url_aviso = "https://www.argenprop.com" + card["href"]
                if url_aviso in vistos:
                    continue
                texto = card.get_text(" ", strip=True)
                address = card.select_one(".card__address")
                title = card.select_one(".card__title--primary, .card__title")
                feats = card.select_one(".card__main-features")
                exp = _RE_EXPENSAS.search(texto)
                casa = _build_casa(
                    "Argenprop", "AP", len(items) + 1, dept, float(card.get("montooperacion") or 0),
                    title.get_text(" ", strip=True) if title else texto[:110],
                    address.get_text(" ", strip=True) if address else "",
                    feats.get_text(" | ", strip=True) if feats else texto,
                    url_aviso,
                    float(exp.group(1).replace(".", "")) if exp else None,
                )
                if casa:
                    vistos.add(url_aviso)
                    items.append(casa)
            if len(cards) < 20:
                break
    return items


BNA_HOGARES = "https://mashogaresconbna.com.ar"
# Los barrios cerrados son tipos aparte en este portal; se suman como "barrio privado/cerrado".
BNA_TIPOS = {"Casa": "", "Casa en barrio privado": "barrio privado", "Casa en barrio de acceso controlado": "barrio cerrado"}


def harvest_bna_hogares() -> list[CasaPro]:
    """Más Hogares con BNA: catálogo de la línea hipotecaria del Banco Nación. Su web
    consulta una API JSON pública (/api/propiedades) con superficie, expensas y coordenadas.
    El servidor a veces responde 408; se reintenta."""
    session = PoliteSession(delay=1.5, timeout=120)
    items: list[CasaPro] = []
    for tipo, extra in BNA_TIPOS.items():
        page, total_pages = 1, 1
        while page <= total_pages:
            data = None
            for intento in range(4):
                try:
                    data = session.get(BNA_HOGARES + "/api/propiedades",
                                       params={"provincia": "Mendoza", "tipo": tipo, "limit": 100, "page": page},
                                       headers={"Accept": "application/json"}).json()["response"]
                    break
                except Exception as e:  # 408 "La operación está tardando más de lo esperado"
                    print(f"[bna-hogares] Reintento ({tipo}, página {page}): {e}")
                    time.sleep(10 * (intento + 1))
            page += 1
            if data is None:
                # Se saltea solo esta página; las demás se siguen pidiendo.
                print(f"[bna-hogares] Sin respuesta para {tipo}, página {page - 1}; la salteo.")
                continue
            total_pages = data.get("totalPages") or total_pages
            for p in data["data"]:
                if p.get("moneda") != "USD" or p.get("estadoReserva") != "Disponible" or not p.get("precio"):
                    continue  # en pesos, reservada o sin precio
                localidad = p.get("localidad") or ""
                # "1ra Sección", "6ta Sección"...: las secciones son de la Ciudad de Mendoza.
                capital = " capital" if re.search(r"\d+\s*(?:ra|da|ta|ma|va|na)\s+secci", localidad, re.I) else ""
                ubicacion = f"{p.get('direccionDescripcion') or ''}, {localidad}{capital}, Mendoza".strip(", ")
                features = " | ".join(x for x in (
                    f"{p['superficieCubierta']} m² cub" if p.get("superficieCubierta") else "",
                    f"{p['superficieTotal']} m² tot" if p.get("superficieTotal") else "",
                    f"{p['dormitorios']} dorm" if p.get("dormitorios") else "",
                    f"{p['banos']} baños" if p.get("banos") else "",
                    f"{p['cocheras']} cochera" if p.get("cocheras") else "",
                    p.get("estadoPropiedad") or "",
                    extra,
                ) if x)
                dept = classify_departamento(f"{localidad}{capital}")
                if dept not in DEPARTAMENTOS:
                    continue  # fuera de las zonas que busca el pipeline (San Rafael, Guaymallén...)
                expensas = p.get("expensas") if p.get("monedaExpensas") == "ARS" else None
                casa = _build_casa(
                    "BNA +Hogares", "BNA", len(items) + 1, dept, float(p["precio"]),
                    p.get("titulo") or f"{tipo} en {localidad}", ubicacion, features,
                    f"{BNA_HOGARES}/propiedad/{p['id']}", expensas, dept_fijo=True,
                )
                if casa:
                    items.append(casa)
    return items


def main():
    print("=" * 80)
    print(f"  INICIANDO PIPELINE PRO DE CASAS EN MENDOZA (≤ {PRECIO_MAX_TXT})")
    print("=" * 80)

    fuentes = [
        ("InMoup (todas las subzonas residenciales)", harvest_inmoup),
        ("Zonaprop (13 subzonas x 2 páginas)", harvest_zonaprop),
        ("MercadoLibre Inmuebles (4 departamentos x 2 páginas)", harvest_mercadolibre),
        ("Argenprop (3 departamentos x 2 páginas, con antibot)", harvest_argenprop),
        ("Más Hogares con BNA (API del catálogo hipotecario)", harvest_bna_hogares),
    ]
    todos: list[CasaPro] = []
    for i, (nombre, harvest) in enumerate(fuentes, 1):
        print(f"\n[Paso {i}/{len(fuentes) + 1}] Extrayendo de {nombre}...")
        props = harvest()
        print(f"           -> {len(props)} propiedades recolectadas")
        todos += props

    # Unir y deduplicar
    unicos: list[CasaPro] = []
    urls_vistas = set()

    for c in todos:
        if c.url and c.url not in urls_vistas:
            urls_vistas.add(c.url)
            unicos.append(c)

    print(f"\n[OK] Total de propiedades únicas en zonas recomendadas: {len(unicos)}")

    print(f"\n[Paso {len(fuentes) + 1}/{len(fuentes) + 1}] Generando informe Excel multipestaña con formato ejecutivo...")
    build_excel_workbook(unicos, "casas_mendoza_recomendadas.xlsx")


if __name__ == "__main__":
    main()
