# SmartWebSearch — Celulares en Argentina

Busca ofertas de celulares en varias tiendas argentinas, las junta en un solo
formato y las ordena por precio.

## Fuentes

| Fuente | Método | Estado |
|---|---|---|
| MercadoLibre | API oficial con `MELI_ACCESS_TOKEN` | Sin token, el listado exige JavaScript (anti-bot) |
| Frávega, Cetrogar, Naldo, Pardo, Coppel, OnCity, Carrefour, Jumbo, Vea, Disco, MasOnline, Tecnocompro | API pública de catálogo de VTEX, con todos los planes de cuotas por tarjeta | Funciona |
| Casa Mendoza, Reig, Luciana Hogar (Mendoza) | Listado de búsqueda de Tiendanube (`data-variants`: precio, descuento efectivo, cuotas por medio de pago) | Funciona |
| Cuyo Digital (Mendoza) | Catálogo embebido en el JS del sitio (efectivo, transferencia, cuotas) | Funciona |
| TecnoMovil (Mendoza) | Catálogo embebido en el payload de Next.js de `/catalogo` | Funciona |
| San José Celulares, Gen Digital, One Store, Claro, Movistar, Musimundo, Megatone… | Cargan los productos desde el navegador o tienen la búsqueda cerrada | Pendiente |

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
python -m smartwebsearch "samsung a56" -c 12   # compara el costo total en 12 cuotas
python -m smartwebsearch "iphone 17 256 -pro -max" --tasa 30   # "-palabra" excluye
```

### Recomendación ("¿cuál conviene?")

Por defecto, el programa recomienda la mejor combinación de **tienda + forma de pago**
comparando todo en *valor presente*. Las cuotas se descuentan a una tasa de
oportunidad mensual: lo que rendiría esa plata si no la gastaras hoy. Contado,
descuento por efectivo/transferencia y cuotas con o sin recargo quedan así en
"pesos de hoy" y se pueden comparar.

- La tasa por defecto es la TNA de plazo fijo a 30 días publicada por el BCRA (API pública).
  Con `--tasa` podés usar la tuya, por ejemplo lo que rinde tu billetera o la inflación esperada.
- Se asume que la primera cuota se paga al mes (primer resumen de la tarjeta).
- Para la opción recomendada, también se muestra qué tasa mensual implícita tienen sus
  cuotas con recargo. Si supera tu tasa, conviene pagar al contado.

Por defecto se descartan los resultados cuyo título no contiene todas las palabras
buscadas. También se descartan los que no están en la categoría pedida, según la ruta
de categoría de cada tienda: `-k/--categoria`, `celulares` por defecto. En esa
categoría quedan afuera los accesorios (fundas, vidrios, cargadores…).

```bash
python -m smartwebsearch "macbook air" -k notebooks
python -m smartwebsearch "funda iphone 17" -k todas   # sin filtro de categoría
python -m smartwebsearch --categoria-default notebooks  # cambia la categoría por defecto
```

La categoría por defecto se guarda en `~/.smartwebsearch.json`. Con `-k` la cambiás
solo para esa búsqueda.

Cada tienda nombra sus categorías a su manera (Cuyo Digital usa "MacBook", no
"notebooks"). Si una tienda no aparece, probá con otro nombre o con `-k todas`.
Con `--todo` se desactivan todos los filtros.

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
