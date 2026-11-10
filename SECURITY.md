# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please do not create a public issue. Instead, email the maintainers at **belentani7pedro@gmail.com**.

## Supported Versions

Only the latest released version of this project is actively supported.

## Scope

Vulnerabilities affecting the codebase or its dependencies are in scope. Issues related to third-party services are the responsibility of their respective maintainers.

## Disclosure Policy

We ask that you report vulnerabilities privately and allow us reasonable time to address them before making any public disclosure.

<!-- repo-forge:security:inicio -->
# Seguridad

## Reportar una vulnerabilidad

No abras un issue público. Usa el canal privado de GitHub Security del repositorio.
Incluye: versión o commit, pasos para reproducir, impacto y, si puedes, una corrección.

## Qué se considera vulnerabilidad

- Ejecución de código o comandos no previstos.
- Lectura o escritura de archivos fuera del alcance declarado.
- Exposición de credenciales en logs, informes o manifiestos.
- Dependencia con CVE conocido en una ruta ejecutable.

## Reglas del proyecto

- Ningún secreto se escribe en disco, en un log ni en un informe.
- Toda operación de escritura requiere `--apply` explícito.
- Las operaciones destructivas están bloqueadas por diseño.

<!-- repo-forge:security -->
<!-- repo-forge:security:fin -->
