import importlib.util
import json
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from ..models import Offer
from .base import Source

SITE_URL = "https://www.gendigital.com.ar/"
WIDGET_ID = "d6d16b0e-5df3-48c9-9519-cd7f2112c464"
BOOT_URL = "https://core.service.elfsight.com/p/boot/"
POSTS_URL = "https://widget-data.service.elfsight.com/api/posts"
ACCOUNT = "gendigital.oficial"  # la otra cuenta del widget es de accesorios
MAX_AGE = timedelta(days=30)  # posts más viejos suelen tener precios vencidos
CACHE_PATH = Path.home() / ".smartwebsearch-gendigital-ocr.json"

ARS_RE = re.compile(r"\$\s*([\d.]{6,})")
USD_RE = re.compile(r"u\$s\s*(\d{3,5})", re.I)
MEMORY_RE = re.compile(r"(\d{1,2})\s*GB\s*[:/]\s*(\d{2,4})\s*(GB|TB)", re.I)


def ocr_available() -> bool:
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


class GenDigital(Source):
    """Gen Digital (Mendoza). No tiene catálogo: su web muestra el feed de Instagram
    con un widget de Elfsight. Los posts se leen del servicio del widget (sin login)
    y el precio, que solo está en la imagen, se saca con OCR (rapidocr, opcional).
    El texto de cada imagen se guarda en CACHE_PATH para no repetir el OCR."""

    name = "gendigital"
    full_catalog = True

    def search(self, query: str, limit: int = 50) -> list[Offer]:
        if not ocr_available():
            raise RuntimeError("necesita OCR: pip install rapidocr-onnxruntime")
        posts = self._recent_posts()[:limit]
        cache = _load_cache()
        ocr = None
        offers = []
        for post in posts:
            key = post["vendorId"]
            if key not in cache:
                url = _image_url(post)
                if url is None:
                    continue
                if ocr is None:
                    from rapidocr_onnxruntime import RapidOCR
                    ocr = RapidOCR()
                    print(f"[{self.name}] leyendo precios con OCR (~10 s por imagen nueva)", file=sys.stderr)
                try:
                    image = self.session.get(url).content
                except requests.HTTPError:
                    continue  # link de Instagram vencido: se reintenta en la próxima corrida
                result, _ = ocr(image)
                cache[key] = " ".join(r[1] for r in result or [])
                _save_cache(cache)  # se guarda de a uno: si se corta, no se pierde lo leído
            offer = parse_post(post, cache[key])
            if offer:
                offers.append(offer)
        return offers

    def _recent_posts(self) -> list[dict]:
        # ponytail: API interna del widget de Elfsight, no documentada; si cambia, se rompe.
        boot = self.session.get(BOOT_URL, params={"page": SITE_URL, "w": WIDGET_ID}).json()
        widget = boot["data"]["widgets"][WIDGET_ID]["data"]
        pids = [s["pid"] for s in widget["settings"]["dataServiceSource"] if s.get("name") == ACCOUNT]
        sources = "&".join(
            "sources[]=" + urllib.parse.quote(json.dumps({"pid": pid, "filters": []}, separators=(",", ":")))
            for pid in pids
        )
        posts = self.session.get(
            f"{POSTS_URL}?{sources}&sort=date&limit=100&offset=0",
            headers={"X-Widget-Token": widget["public_widget_token"], "Origin": SITE_URL.rstrip("/")},
        ).json()["payload"]
        cutoff = datetime.now(timezone.utc) - MAX_AGE
        return [p for p in posts if datetime.fromisoformat(p["publishedAt"]) >= cutoff]


def _image_url(post: dict) -> str | None:
    media = (post.get("media") or [{}])[0]
    return (media.get("thumbnail") or (media.get("cover") or {}).get("thumbnail") or {}).get("url")


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    # Archivo temporal + replace: un Ctrl+C a mitad de la escritura no deja el caché cortado.
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_PATH)


def parse_post(post: dict, ocr_text: str) -> Offer | None:
    """Modelo del hashtag del texto ("#PocoX8PROMAX✅ ..."), precio y memoria de la imagen."""
    ars = ARS_RE.search(ocr_text)
    model = re.match(r"\s*#?\s*([^\n✅]+?)\s*(?:✅|\.\.|\n|$)", post.get("caption") or "")
    if ars is None or model is None:
        return None
    title = model.group(1)
    memory = MEMORY_RE.search(ocr_text)
    if memory:
        title += f" {memory.group(1)}GB {memory.group(2)}{memory.group(3).upper()}"
    usd = USD_RE.search(ocr_text)
    return Offer(
        source="gendigital",
        title=title,
        price=float(ars.group(1).replace(".", "")),
        url=post.get("link", SITE_URL),
        seller="Gen Digital" + (f" (USD {usd.group(1)})" if usd else ""),
        condition="new",  # "todo es nuevo, facturado, sellado"
        category="/Celulares/",
    )
