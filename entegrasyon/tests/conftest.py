"""Tüm entegrasyon testleri için ortak ayar: gelen-istek arşivi (istek_arsivi.py) ve diğer kalıcı dizinler gerçek
sistem geçici dizinine değil, her testin kendi geçici dizinine yazılır (aksi halde TestClient istekleri `/tmp`'yi kirletir)."""

import pytest


@pytest.fixture(autouse=True)
def _veri_dizini_izole(tmp_path, monkeypatch):
    monkeypatch.setenv("ONBOARD_DATA_DIR", str(tmp_path / "onboard-veri-kok"))
