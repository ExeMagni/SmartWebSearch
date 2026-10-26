"""
InMoup — portal inmobiliario de Argentina.

Scrapes páginas de listado (/casas-en-venta-en-{zona}) vía HTML.
Cada zona devuelve 24 propiedades (primer página; InMoup usa CSR para las demás).

Uso como Source estándar: search() recibe el slug de zona (ej. "godoy-cruz")
y devuelve hasta `limit` propiedades.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

from ..http import PoliteSession

BASE_URL = "https://inmoup.com.ar"

# Zonas de interés para Mendoza Gran Sur
MENDOZA_ZONAS = {
    "godoy-cruz": "casas-en-venta-en-godoy-cruz",
    "lujan-de-cuyo": "casas-en-venta-en-lujan-de-cuyo",
    "maipu": "casas-en-venta-en-maipu",
    # Cuarta Sección es un barrio dentro de la ciudad de Mendoza
    "cuarta-seccion": "casas-en-venta-en-cuarta-seccion",
    # Fallbacks genéricos si los anteriores no tienen listado propio
    "mendoza-ciudad": "casas-en-venta-en-mendoza",
}

import unicodedata

# Barrios/zonas a excluir por seguridad — match normalizado sobre título o ubicación
ZONAS_EXCLUIDAS: list[str] = [
    # Godoy Cruz
    "villa hipodromo",
    "hipodromo",
    "campo pappa",
    "la gloria",
    "tres estrellas",
    "barrio sarmiento",
    "piedrabuena",
    # Luján de Cuyo / Límites
    "cuadro estacion",
    "costanera",
    # Maipú
    "barrio renacer",
    "barrio soberania nacional",
    "barrio triple",
    # Capital / Las Heras (límites Cuarta Sección / Parque)
    "barrio san martin",
    "barrio olivares",
    "barrio flores",
    "santa teresita",
]


@dataclass
class Propiedad:
    """Propiedad inmobiliaria scrapeada de InMoup."""

    fuente: str = "inmoup"
    titulo: str = ""
    precio_usd: Optional[float] = None
    m2_cubiertos: Optional[float] = None
    m2_totales: Optional[float] = None
    precio_por_m2: Optional[float] = None  # calculado
    ubicacion: str = ""
    dormitorios: Optional[int] = None
    banos: Optional[int] = None
    url: str = ""
    descripcion: str = ""
    excluida: bool = False        # True si cae en una zona excluida
    razon_exclusion: str = ""

    def to_dict(self) -> dict:
        return {
            "fuente": self.fuente,
            "titulo": self.titulo,
            "precio_usd": self.precio_usd,
            "m2_cubiertos": self.m2_cubiertos,
            "m2_totales": self.m2_totales,
            "precio_por_m2": self.precio_por_m2,
            "ubicacion": self.ubicacion,
            "dormitorios": self.dormitorios,
            "banos": self.banos,
            "url": self.url,
            "excluida": self.excluida,
            "razon_exclusion": self.razon_exclusion,
        }


# ---------- helpers de parseo ---------------------------------------------------

_RE_PRECIO = re.compile(r'US\$\s*([\d\.,]+)', re.I)
_RE_M2 = re.compile(r'([\d\.,]+)\s*m[²2²]', re.I)
_RE_NUMERO = re.compile(r'(\d+(?:[.,]\d+)?)')


def _parse_float(text: str) -> Optional[float]:
    """'145.000' o '145,5' → float."""
    clean = text.strip().replace(".", "").replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return None


def _parse_price(text: str) -> Optional[float]:
    m = _RE_PRECIO.search(text)
    if m:
        return _parse_float(m.group(1))
    return None


def _parse_m2_values(text: str) -> tuple[Optional[float], Optional[float]]:
    """Devuelve (cubiertos, totales) del texto del artículo.

    InMoup muestra cubiertos primero, luego totales.
    Filtra valores fuera del rango razonable (5–2000 m²).
    Garantiza cubiertos ≤ totales.
    """
    raw = _RE_M2.findall(text)
    # Filtrar valores razonables para propiedades residenciales
    matches = [v for v in raw if 5 <= (_parse_float(v) or 0) <= 2000]
    cubiertos = _parse_float(matches[0]) if len(matches) >= 1 else None
    totales = _parse_float(matches[1]) if len(matches) >= 2 else None
    # Si los valores parecen invertidos (cubiertos > totales), corregir
    if cubiertos is not None and totales is not None and cubiertos > totales:
        cubiertos, totales = totales, cubiertos
    return cubiertos, totales


def _normalize_str(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _is_zona_excluida(texto: str, zonas: list[str] = ZONAS_EXCLUIDAS) -> tuple[bool, str]:
    texto_norm = _normalize_str(texto)
    for zona in zonas:
        if _normalize_str(zona) in texto_norm:
            return True, zona
    return False, ""


def _parse_article(article, zona_slug: str) -> Propiedad:
    """Extrae datos de un <article> de InMoup."""
    prop = Propiedad()

    # URL — primer <a> con /ficha/ en el href
    for a in article.find_all("a", href=True):
        href = a.get("href", "")
        if "/ficha/" in href or "/inmuebles/" in href:
            prop.url = BASE_URL + href if not href.startswith("http") else href
            break

    # Texto completo del artículo para extraer precio, m², dormitorios, etc.
    texto = article.get_text(separator=" ", strip=True)

    # Precio
    prop.precio_usd = _parse_price(texto)

    # m²
    prop.m2_cubiertos, prop.m2_totales = _parse_m2_values(texto)

    # Precio por m² (usando cubiertos preferentemente)
    ref_m2 = prop.m2_cubiertos or prop.m2_totales
    if prop.precio_usd and ref_m2:
        prop.precio_por_m2 = round(prop.precio_usd / ref_m2, 0)

    # Título — texto del primer <p> o texto largo
    p_tags = article.find_all("p")
    for p in p_tags:
        t = p.get_text(strip=True)
        if len(t) > 20 and "US$" not in t:
            prop.titulo = t[:120]
            prop.descripcion = t[:500]
            break

    # Ubicación — buscar elemento que contenga nombre de ciudad/barrio
    # En InMoup está en los alt de las imágenes o en un <p> con la zona
    img = article.find("img")
    if img and img.get("alt"):
        prop.ubicacion = img.get("alt", "").strip()

    # Si la ubicación está vacía, intentar extraer del texto
    if not prop.ubicacion:
        # Buscar patrones como "Godoy Cruz, Mendoza" o "Barrio X, Ciudad"
        loc_match = re.search(r'((?:Barrio|B[°º])\s+[^,\n]+|Godoy Cruz|Luján de Cuyo|Maipú|Mendoza(?:\s+Capital)?)[,\s]', texto, re.I)
        if loc_match:
            prop.ubicacion = loc_match.group(0).strip(", ")

    # Zona slug como fallback de ubicación
    if not prop.ubicacion:
        prop.ubicacion = zona_slug

    # Verificar exclusión
    texto_check = f"{prop.titulo} {prop.ubicacion} {prop.descripcion}"
    excluida, razon = _is_zona_excluida(texto_check)
    prop.excluida = excluida
    prop.razon_exclusion = razon

    return prop


# ---------- función principal de scraping ----------------------------------------

def scrape_zona(
    zona_slug: str,
    session: Optional[PoliteSession] = None,
    max_precio_usd: float = 150_000,
    incluir_sin_precio: bool = False,
) -> list[Propiedad]:
    """
    Scrape una zona de InMoup y devuelve las propiedades filtradas.

    Args:
        zona_slug: clave de MENDOZA_ZONAS (ej. "godoy-cruz") o slug directo
                   (ej. "casas-en-venta-en-godoy-cruz").
        session: PoliteSession reutilizable; crea una nueva si no se pasa.
        max_precio_usd: precio máximo en dólares (default 150k).
        incluir_sin_precio: si True, incluye propiedades sin precio detectado.

    Returns:
        Lista de Propiedad, incluyendo las excluidas (excluida=True) para
        que el llamante pueda mostrarlas aparte si quiere.
    """
    session = session or PoliteSession()
    path = MENDOZA_ZONAS.get(zona_slug, zona_slug)
    url = f"{BASE_URL}/{path}"

    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    propiedades: list[Propiedad] = []
    for article in soup.find_all("article"):
        prop = _parse_article(article, zona_slug)

        # Filtrar por precio
        if prop.precio_usd is None:
            if not incluir_sin_precio:
                continue
        elif prop.precio_usd > max_precio_usd:
            continue

        propiedades.append(prop)

    return propiedades


def scrape_todas_las_zonas(
    zonas: Optional[list[str]] = None,
    session: Optional[PoliteSession] = None,
    max_precio_usd: float = 150_000,
) -> list[Propiedad]:
    """Scrape múltiples zonas (default: todas las de MENDOZA_ZONAS)."""
    session = session or PoliteSession()
    zonas = zonas or list(MENDOZA_ZONAS.keys())
    resultados: list[Propiedad] = []
    for zona in zonas:
        try:
            props = scrape_zona(zona, session=session, max_precio_usd=max_precio_usd)
            resultados.extend(props)
        except Exception as e:
            print(f"[inmoup] Error scraping {zona}: {e}")
    return resultados
