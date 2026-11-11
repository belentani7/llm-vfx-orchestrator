

<!-- repo-forge:docs-operacion:inicio -->
# Operación

## Rutina

| Cuándo | Qué | Comando |
|---|---|---|
| Antes de cambiar | Línea base | `python scripts/doctor.py` |
| Durante | Un cambio verificable | — |
| Antes de entregar | Gate + tests | `python scripts/doctor.py` y tests |
| Al publicar | Revisar `plataforma/PAYWALL.md` | — |

## Incidentes

1. Reproducir con el mínimo caso.
2. Comprobar si el gate lo detectaba; si no, añadir la comprobación.
3. Corregir, volver a ejecutar, anotar en `CHANGELOG.md`.

## Copias

Nada se borra: los descartes van a `quarantine/` con fecha. Las copias de seguridad se
hacen por git, no por duplicado manual.

<!-- repo-forge:operacion -->
<!-- repo-forge:docs-operacion:fin -->
