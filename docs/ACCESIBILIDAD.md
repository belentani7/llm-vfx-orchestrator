

<!-- repo-forge:docs-accesibilidad:inicio -->
# Accesibilidad

Objetivo: WCAG 2.2 AA en las superficies públicas.

## Estado

Sin fallos de accesibilidad detectados por el gate en la última pasada.

## Compromisos

- Un solo `h1` por página y jerarquía sin saltos.
- Todo control interactivo es nativo (`a`, `button`, `input` con `label`).
- Foco visible y navegación completa por teclado.
- Respeto a `prefers-reduced-motion`.
- Texto alternativo en imágenes con contenido; `alt=""` en las decorativas.

## Cómo se comprueba

```bash
python scripts/doctor.py     # reglas ACC-*
```

<!-- repo-forge:accesibilidad -->
<!-- repo-forge:docs-accesibilidad:fin -->
