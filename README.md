# SmartWebSearch — Celulares en Argentina

Busca ofertas de celulares en varias tiendas argentinas, las junta en un solo
formato y las ordena por precio.

## Fuentes

| Fuente | Método | Estado |
|---|---|---|
| MercadoLibre | API oficial si hay `MELI_ACCESS_TOKEN`; si no, listado HTML | Parser probado con fixtures |
| Carrefour, OnCity | API pública de catálogo de VTEX | Parser probado con fixtures |
| Frávega, Musimundo, Cetrogar, Garbarino… | Pendiente (cada una necesita su propio adaptador) | — |

Para agregar otra tienda que use VTEX alcanza con sumarla a `VTEX_STORES` en
`smartwebsearch/sources/vtex.py`. Para otras plataformas hay que crear una
clase que herede de `Source` e implemente `search()`.

## Uso

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m smartwebsearch "samsung galaxy a55"
python -m smartwebsearch "iphone 15 128gb" -s mercadolibre --max-price 1500000
python -m smartwebsearch "motorola g85" -o resultados/motorola.csv
```

### Token de MercadoLibre (recomendado)

MercadoLibre pide autenticación para usar su API de búsqueda. Para obtener un token:
1. Creá una aplicación en <https://developers.mercadolibre.com.ar/devcenter>.
2. Generá un access token (OAuth) y exportalo con `export MELI_ACCESS_TOKEN=...`.

Si no hay token, se usa el listado HTML. Funciona igual, pero es más frágil:
si MercadoLibre cambia el diseño de la página, el parser deja de andar.

## Tests

```bash
pytest
```

Los tests usan respuestas de ejemplo guardadas en `tests/fixtures/`, así que no
necesitan conexión a internet.

## Buenas prácticas

- El cliente HTTP espera al menos 1,5 s entre requests (`PoliteSession`).
- Siempre que exista, usar la API oficial antes que el HTML.
- Revisar el `robots.txt` y los términos de uso de cada sitio. Es solo para uso personal o de investigación.
