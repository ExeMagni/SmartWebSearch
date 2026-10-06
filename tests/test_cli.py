import pytest

from smartwebsearch import cli


def test_categoria_default_se_guarda(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    assert cli.load_config() == {}

    assert cli.main(["--categoria-default", "notebooks"]) == 0
    assert cli.load_config() == {"categoria": "notebooks"}

    with pytest.raises(SystemExit):  # sin búsqueda ni --categoria-default
        cli.main([])
