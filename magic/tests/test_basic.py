from __future__ import annotations

import json
from pathlib import Path


def test_magic_catalog_and_shaders_exist() -> None:
    magic_dir = Path(__file__).resolve().parent.parent
    catalog = magic_dir / "data" / "catalogo.json"
    assert catalog.is_file()
    data = json.loads(catalog.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert (magic_dir / "shader.html").is_file()
    assert (magic_dir / "immersive.html").is_file()
