"""Tests for scripts/repair_pages.py — family HTML repair and idempotency."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("repair_pages", ROOT / "scripts" / "repair_pages.py")
assert SPEC and SPEC.loader
repair_pages = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair_pages)


def test_repair_one_collapses_nested_landmarks_and_is_idempotent() -> None:
    corrupted = """<!doctype html>
<html lang="es">
<body>
  <header class="site"><header class="dup"><a href=""> Rota </a></header></header>
  <html><body>
  <main id="a"><main id="b"><h1>Título</h1><p class="note">$structure_note</p></main></main>
  <section class="webgl-lab" data-webgl-lab><h2>Lab</h2></section>
  <style>.webgl-lab { margin: 0; }</style>
  <script>(() => { const x = "[data-webgl-lab]"; })();</script>
  <footer><footer>Pie</footer></footer>
  </body></html>
</body>
</html>
"""
    once = repair_pages.repair_one(corrupted)
    twice = repair_pages.repair_one(once)

    assert once == twice, "repair_one must be strictly idempotent"
    assert once.count("<header") == 1
    assert once.count("</header>") == 1
    assert once.count("<main") == 1
    assert once.count("</main>") == 1
    assert once.count("<footer") == 1
    assert once.count("</footer>") == 1
    assert once.count("<html") == 1
    assert once.count("<body") == 1
    assert 'href="#" data-broken="true"' in once
    assert "data-webgl-lab" not in once
    assert "$structure_note" not in once


def test_repository_html_pages_pass_check_mode() -> None:
    exit_code = repair_pages.main([str(ROOT), "--check"])
    assert exit_code == 0
