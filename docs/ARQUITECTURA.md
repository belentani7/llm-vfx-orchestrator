

<!-- repo-forge:docs-arquitectura:inicio -->
# Arquitectura

## Tipo

aplicación web con build (Next/Vite/Expo)

## Piezas observadas

| Pieza | Evidencia |
|---|---|
| Lenguajes | Python 47.5%, JSON 20.7%, HTML 13.0%, Markdown 6.7%, TypeScript 6.0%, CSS 3.9% |
| Puntos de entrada | orchestrator/cli.py |
| Páginas HTML | 8 |
| Tests | 13 archivos |
| Dependencias de paquete | 2 |

## Capas propuestas

```text
contenido/      datos y textos versionados
plataforma/     ficha, diseño y contrato del producto
brand/          tokens, marca y activos
scripts/        verificación y operación
tests/          pruebas ejecutables
```

La propuesta no mueve archivos existentes: describe dónde debe vivir lo nuevo para que
el repositorio siga siendo legible.

## Deuda declarada

- 6 lenguajes: coste de contexto alto.

<!-- repo-forge:arquitectura -->
<!-- repo-forge:docs-arquitectura:fin -->
