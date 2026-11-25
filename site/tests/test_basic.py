from __future__ import annotations

import json
from pathlib import Path


def test_site_catalog_and_index_exist() -> None:
    site_dir = Path(__file__).resolve().parent.parent
    catalog = site_dir / "data" / "catalogo.json"
    assert catalog.is_file()
    data = json.loads(catalog.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert (site_dir / "index.html").is_file()
