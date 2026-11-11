

<!-- repo-forge:docs-modelo-de-datos:inicio -->
# Modelo de datos

## Entidades

| Entidad | Campos clave | Dónde vive |
|---|---|---|
| Producto | nombre, tipo, modelo, público | `data/catalogo.json` |
| Medida | archivos, líneas, html, tests | `data/catalogo.json` → `medido` |
| Paleta | bg, ink, accent | `brand/tokens.json` |
| Fase | número, nombre, gratis, pago, gate | `plataforma/paywall.json` |
| Recurso | ruta, tipo, origen | `plataforma/recursos.json` |

## Regla

Un dato se escribe **una vez**. Si aparece en dos sitios y no coinciden, gana
`data/catalogo.json` y el otro se corrige.

<!-- repo-forge:modelo-datos -->
<!-- repo-forge:docs-modelo-de-datos:fin -->
