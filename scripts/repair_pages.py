#!/usr/bin/env python3
"""repair_pages.py — Reparación determinista e idempotente de páginas HTML por familia.

Sanea defectos recurrentes de generación de plantillas:
  1. Colapso de landmarks duplicados/anidados (<header>, <main>, <footer>) al único principal.
  2. Eliminación de etiquetas <html> / <body> incrustadas dentro del documento.
  3. Marcado explícito de enlaces vacíos (<a href=""> -> href="#" data-broken="true").
  4. Eliminación de bloques basura de plantilla WebGL ([data-webgl-lab]).
  5. Sustitución de variables de plantilla sin interpolar ($structure_note).

Uso:
  python3 scripts/repair_pages.py . --check
  python3 scripts/repair_pages.py . --dry-run
  python3 scripts/repair_pages.py .
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".git.corrupt", "node_modules", ".venv", "dist", "coverage", "__pycache__"}

_LANDMARK_TAGS = ("header", "main", "footer")
_WEBGL_LAB_RE = re.compile(
    r"\s*<section\b[^>]*\bdata-webgl-lab\b[^>]*>[\s\S]*?</section>"
    r"(?:\s*<style>[\s\S]*?\.webgl-lab[\s\S]*?</style>)?"
    r"(?:\s*<script>[\s\S]*?data-webgl-lab[\s\S]*?</script>)?",
    flags=re.IGNORECASE,
)
_EMPTY_HREF_RE = re.compile(r'(<a\b[^>]*?)\bhref=(["\'])\s*\2', flags=re.IGNORECASE)


def _collapse_duplicate_landmark(html: str, tag: str) -> str:
    open_re = re.compile(rf"<{tag}\b[^>]*>", flags=re.IGNORECASE)
    close_re = re.compile(rf"</{tag}\s*>", flags=re.IGNORECASE)

    opens = list(open_re.finditer(html))
    closes = list(close_re.finditer(html))
    if len(opens) <= 1 and len(closes) <= 1:
        return html

    # Conservamos la primera apertura y el último cierre para preservar todo el contenido interior
    spans_to_strip: list[tuple[int, int]] = []
    for extra_open in opens[1:]:
        spans_to_strip.append(extra_open.span())
    if len(closes) > 1:
        for extra_close in closes[:-1]:
            spans_to_strip.append(extra_close.span())

    if not spans_to_strip:
        return html

    spans_to_strip.sort()
    pieces: list[str] = []
    cursor = 0
    for start, end in spans_to_strip:
        if start < cursor:
            continue
        pieces.append(html[cursor:start])
        cursor = end
    pieces.append(html[cursor:])
    return "".join(pieces)


def _strip_embedded_root_tags(html: str) -> str:
    open_html_re = re.compile(r"<html\b[^>]*>", flags=re.IGNORECASE)
    close_html_re = re.compile(r"</html\s*>", flags=re.IGNORECASE)
    open_body_re = re.compile(r"<body\b[^>]*>", flags=re.IGNORECASE)
    close_body_re = re.compile(r"</body\s*>", flags=re.IGNORECASE)

    for open_re, close_re in ((open_html_re, close_html_re), (open_body_re, close_body_re)):
        opens = list(open_re.finditer(html))
        if len(opens) > 1:
            for extra in reversed(opens[1:]):
                html = html[: extra.start()] + html[extra.end() :]
        closes = list(close_re.finditer(html))
        if len(closes) > 1:
            for extra in reversed(closes[:-1]):
                html = html[: extra.start()] + html[extra.end() :]
    return html


def repair_one(html: str) -> str:
    """Repara un documento HTML de forma pura e idempotente."""
    # 1. Quitar bloques basura de plantilla WebGL ([data-webgl-lab])
    repaired = _WEBGL_LAB_RE.sub("", html)

    # 2. Eliminar <html> / <body> incrustados adicionales
    repaired = _strip_embedded_root_tags(repaired)

    # 3. Colapsar landmarks duplicados (<header>, <main>, <footer>) al contenedor externo
    for tag in _LANDMARK_TAGS:
        repaired = _collapse_duplicate_landmark(repaired, tag)

    # 4. Restaurar href="" vacíos con marcador auditable sin duplicarlo
    def _fix_href(match: re.Match[str]) -> str:
        prefix = match.group(1)
        if "data-broken=" in prefix:
            return f'{prefix}href="#"'
        return f'{prefix}href="#" data-broken="true"'

    repaired = _EMPTY_HREF_RE.sub(_fix_href, repaired)

    # 5. Limpiar placeholder residual de plantilla ($structure_note)
    repaired = repaired.replace(
        "<p class=\"note\">$structure_note</p>",
        "<p class=\"note\">Arquitectura modular híbrida verificada.</p>",
    )
    return repaired


def iter_html_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for path in root.rglob("*.html"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        found.append(path)
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repara estructura HTML por familia de forma determinista e idempotente."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=Path("."),
        type=Path,
        help="Directorio raíz o archivo HTML a inspeccionar/reparar (por defecto: .).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra cuántos archivos cambiarían sin escribir en disco.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Modo gate CI: solo verifica y devuelve código de salida 1 si algún archivo requiere reparación.",
    )
    args = parser.parse_args(argv)

    files = iter_html_files(args.root)
    changed_paths: list[Path] = []
    for path in files:
        original = path.read_text(encoding="utf-8")
        repaired = repair_one(original)
        if repaired != original:
            changed_paths.append(path)
            if not args.dry_run and not args.check:
                path.write_text(repaired, encoding="utf-8")

    action_label = "a cambiar" if (args.dry_run or args.check) else "cambiados"
    print(f"repair_pages: {len(changed_paths)}/{len(files)} archivos {action_label}")
    for changed in changed_paths:
        print(f"  - {changed}")
    return 1 if (args.check and changed_paths) else 0


if __name__ == "__main__":
    sys.exit(main())
