import time

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}


class PoliteSession:
    """Sesión HTTP con pausa mínima entre requests para no saturar a las tiendas."""

    def __init__(self, delay: float = 1.5, timeout: float = 20.0):
        self.delay = delay
        self.timeout = timeout
        self._last = 0.0
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

    def get(self, url: str, **kwargs) -> requests.Response:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        kwargs.setdefault("timeout", self.timeout)
        resp = self._session.get(url, **kwargs)
        self._last = time.monotonic()
        resp.raise_for_status()
        return resp
