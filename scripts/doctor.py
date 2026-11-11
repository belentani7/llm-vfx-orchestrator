"""Doctor del repositorio: comprueba estructura, reglas y banco de datos.
Solo lectura. Código de salida 1 si hay fallos.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "README.md", "LICENSE", "BIBLIA.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "SECURITY.md", "CHANGELOG.md", "AGENTS.md", ".editorconfig", ".gitattributes",
    "data/catalogo.json", "brand/tokens.json", "plataforma/FICHA.md",
    "plataforma/PLATAFORMA.md", "plataforma/PAYWALL.md", "plataforma/RECURSOS.md",
]


def check() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    for rel in REQUIRED:
        p = ROOT / rel
        out.append((f"existe {rel}", p.is_file(), "" if p.is_file() else "falta"))

    cat = ROOT / "data" / "catalogo.json"
    if cat.is_file():
        try:
            data = json.loads(cat.read_text(encoding="utf-8"))
            out.append(("catalogo.json válido", "nombre" in data and "medido" in data, ""))
        except json.JSONDecodeError as exc:
            out.append(("catalogo.json válido", False, str(exc)))

    readme = ROOT / "README.md"
    if readme.is_file():
        txt = readme.read_text(encoding="utf-8", errors="replace")
        out.append(("README con contenido", len(txt.splitlines()) >= 10, f"{len(txt.splitlines())} líneas"))
        out.append(("README cita la ficha", "plataforma/FICHA.md" in txt, ""))

    for html in list(ROOT.glob("*.html"))[:40]:
        txt = html.read_text(encoding="utf-8", errors="replace")
        out.append((f"{html.name}: doctype", bool(re.match(r"\s*<!doctype html", txt, re.I)), ""))
        out.append((f"{html.name}: lang", bool(re.search(r"<html[^>]+lang=", txt, re.I)), ""))
        out.append((f"{html.name}: viewport", bool(re.search(r"name=[\"']viewport", txt, re.I)), ""))

    tokens = ROOT / "brand" / "tokens.json"
    if tokens.is_file():
        try:
            t = json.loads(tokens.read_text(encoding="utf-8"))
            out.append(("tokens con paleta", "paleta" in t, ""))
        except json.JSONDecodeError:
            out.append(("tokens con paleta", False, "json inválido"))
    return out


def main() -> int:
    results = check()
    bad = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(("OK   " if ok else "FALLA ") + name + (f"  ({detail})" if detail else ""))
    print(f"\n{len(results) - len(bad)}/{len(results)} comprobaciones en verde")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
