import pytest

from smartwebsearch import cli


def test_categoria_default_se_guarda(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    assert cli.load_config() == {}

    assert cli.main(["--categoria-default", "notebooks"]) == 0
    assert cli.load_config() == {"categoria": "notebooks"}

    with pytest.raises(SystemExit):  # sin búsqueda ni --categoria-default
        cli.main([])


def test_compara_varias_busquedas(tmp_path, monkeypatch, capsys):
    from smartwebsearch.models import Offer
    from smartwebsearch.sources.base import Source

    class Catalogo(Source):
        name = "catalogo"
        full_catalog = True
        calls = 0

        def search(self, query, limit=50):
            Catalogo.calls += 1
            return [
                Offer("catalogo", "Samsung Galaxy S25 256GB", 1_500_000, "u1", category="/Celulares/"),
                Offer("catalogo", "Samsung Galaxy S25 FE 128GB", 900_000, "u2", category="/Celulares/"),
                Offer("catalogo", "iPhone 15 Pro Max 256GB", 1_100_000, "u3", category="/Celulares/"),
            ]

    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "available_sources", lambda: {"catalogo": Catalogo()})
    monkeypatch.setattr(cli, "default_sources", lambda sources: ["catalogo"])

    assert cli.main(["samsung s25 -fe", "iphone 15 pro max", "pixel 9", "--tasa", "30"]) == 0
    out = capsys.readouterr().out
    assert Catalogo.calls == 1  # el catálogo se baja una vez para las tres búsquedas
    assert '>> De estas opciones conviene "iphone 15 pro max"' in out
    assert '$400,000 menos que la siguiente, "samsung s25 -fe"' in out  # el FE quedó excluido
    assert "Sin resultados: pixel 9" in out


def test_ctrl_c_corta_sin_esperar_a_las_tiendas(tmp_path, monkeypatch):
    import _thread
    import threading
    import time

    from smartwebsearch.sources.base import Source

    stop = threading.Event()

    class Lenta(Source):
        name = "lenta"

        def search(self, query, limit=50):
            stop.wait(10)  # una tienda que tarda mucho
            return []

    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "available_sources", lambda: {"lenta": Lenta()})
    monkeypatch.setattr(cli, "default_sources", lambda sources: ["lenta"])

    def fake_exit(code):
        raise SystemExit(code)

    monkeypatch.setattr(cli.os, "_exit", fake_exit)
    threading.Timer(0.3, _thread.interrupt_main).start()  # como apretar Ctrl+C
    start = time.monotonic()
    try:
        with pytest.raises(SystemExit) as exc:
            cli.main(["iphone 15", "--tasa", "30"])
    finally:
        stop.set()
    assert exc.value.code == 130
    assert time.monotonic() - start < 2


def test_is_used():
    from smartwebsearch.models import Offer

    def offer(title, condition="new"):
        return Offer("x", title, 1, "u", condition=condition)

    assert cli.is_used(offer("iPhone 15 128 GB", condition="used"))
    assert cli.is_used(offer("Reacondicionado Samsung Galaxy S24 Plus"))  # Frávega lo marca "new"
    assert cli.is_used(offer("IPHONE 13 USADO GRADO A+ 128GB"))
    assert cli.is_used(offer("Motorola G35 - Semi Nuevo"))
    assert not cli.is_used(offer("Samsung Galaxy S25 256GB"))
    assert not cli.is_used(offer("Samsung Galaxy S25", condition=None))
    assert not cli.is_used(offer("Celular con cargador integrado", condition="nuevo"))
