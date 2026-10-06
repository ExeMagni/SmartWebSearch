# SmartWebSearch — Celulares en Argentina

Busca ofertas de celulares en varias tiendas argentinas, las junta en un solo
formato y las ordena por precio.

## Fuentes

| Fuente | Método | Estado |
|---|---|---|
| MercadoLibre | API oficial de catálogo (`/products/search` + ofertas de cada producto), con credenciales en `.env` | A pedido: `--mercadolibre` |
| Frávega, Cetrogar, Naldo, Pardo, Coppel, OnCity, Carrefour, Jumbo, Vea, Disco, MasOnline, Tecnocompro | API pública de catálogo de VTEX, con todos los planes de cuotas por tarjeta | Funciona |
| Casa Mendoza, Reig, Luciana Hogar (Mendoza) | Listado de búsqueda de Tiendanube (`data-variants`: precio, descuento efectivo, cuotas por medio de pago) | Funciona |
| Cuyo Digital (Mendoza) | Catálogo embebido en el JS del sitio (efectivo, transferencia, cuotas) | Funciona |
| TecnoMovil (Mendoza) | Catálogo embebido en el payload de Next.js de `/catalogo` | Funciona |
| TecPhone (Mendoza, @tec_phone.ar) | Planilla pública de Google Sheets de la bio de Instagram (precio en pesos y USD, disponibilidad, batería de los usados) | Funciona |
| Mendofix (Mendoza) | Página de WordPress/Elementor con precios en USD, pasados a pesos con el dólar blue ([dolarapi.com](https://dolarapi.com)) | Funciona |
| SEN Computación | JSON de la categoría Celulares de Empretienda; saltea lo que no tiene stock | Funciona (hoy todo sin stock) |
| Gen Digital (Mendoza) | Feed de Instagram del widget de su web; el precio sale de la imagen con OCR | Opcional: `pip install rapidocr-onnxruntime` |
| Xiaomi Store (tienda oficial) | Búsqueda JSON de PrestaShop (`ajax=1`); saltea lo "Agotado", toma las cuotas sin interés y la memoria de la URL | Funciona |
| Musimundo | Sitio en mantenimiento | Pendiente |
| Tienda BNA | La API de búsqueda pide una clave interna de la web (`401 Bad credentials`) | No disponible |
| San José Celulares, One Store, Claro, Movistar, Megatone… | Cargan los productos desde el navegador o tienen la búsqueda cerrada | Pendiente |

Las ofertas sin stock (o vendidas/reservadas, en TecPhone) se descartan automáticamente
en cada tienda que informa el stock.

Para agregar otra tienda que use VTEX alcanza con sumarla a `VTEX_STORES` en
`smartwebsearch/sources/vtex.py`. Para otras plataformas hay que crear una
clase que herede de `Source` e implemente `search()`.

## Uso

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m smartwebsearch "samsung galaxy a55"
python -m smartwebsearch "iphone 15 128gb" --mercadolibre --max-price 1500000
python -m smartwebsearch "motorola g85" -o resultados/motorola.csv
python -m smartwebsearch "samsung a56" -c 12   # compara el costo total en 12 cuotas
python -m smartwebsearch "iphone 17 256 -pro -max" --tasa 30   # "-palabra" excluye
python -m smartwebsearch "samsung s25 -fe" "iphone 15 pro max"   # compara: ¿cuál conviene?
python -m smartwebsearch "iphone 15" "iphone 16" --nuevo   # solo nuevos (--usado: solo usados)
```

`--nuevo` deja afuera los usados y reacondicionados, y `--usado` muestra solo esos. Se
decide por la condición que informa la tienda y, como muchas marcan todo como nuevo,
también por el título ("usado", "reacondicionado", "seminuevo"…).

Con varias búsquedas se muestran las mejores opciones de cada una (`--top`, 5 por defecto)
y al final una comparación con la mejor de cada búsqueda y cuál conviene. Las tiendas
que bajan su catálogo entero se consultan una sola vez por corrida.

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

### MercadoLibre

No corre por defecto porque es lento: hace un request por cada producto del catálogo.
Se suma con `--mercadolibre` (o con `-s mercadolibre`).

1. Creá una aplicación en <https://developers.mercadolibre.com.ar/devcenter>.
2. Copiá el Client ID y el Client Secret al archivo `.env` de la raíz del proyecto
   (no se sube a git):
   ```
   MELI_CLIENT_ID=...
   MELI_CLIENT_SECRET=...
   ```
   El programa pide el token solo (`client_credentials`), no hace falta autorizar nada.

`/sites/MLA/search` responde 403 a las apps comunes, así que se busca en el catálogo
(`/products/search`, solo celulares) y se piden las ofertas de cada producto. Sin
credenciales se intenta el listado HTML, que suele bloquear el antibot.

### Gen Digital (OCR)

Gen Digital publica los precios solo dentro de las imágenes de Instagram. Si instalás
`rapidocr-onnxruntime`, se suma a la búsqueda por defecto. La primera vez tarda
unos 10 s por publicación. Después, el texto leído queda guardado en
`~/.smartwebsearch-gendigital-ocr.json` y solo se procesan las publicaciones nuevas.
Se usan las publicaciones de los últimos 30 días.

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
