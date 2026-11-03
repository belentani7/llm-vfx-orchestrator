# Protocolo de auditoría de seguridad (R1–R8)

Obligatorio antes de cualquier merge a `main` en repositorios de `@belentani7`.

## R1 — Cero secretos en el repositorio

- Prohibido commitear claves, tokens, contraseñas, cadenas de conexión o certificados.
- `.gitleaks.toml` debe incluir `[extend] useDefault = true` y no puede tener allowlists globales.
- Verificación: `gitleaks detect --source . --redact --no-banner`.

## R2 — Nada de TypeScript sin compilar en producción

- Producción ejecuta JavaScript compilado; `tsx`, `ts-node` y `vite dev` son solo desarrollo.
- El pipeline debe construir (`pnpm build` o equivalente) y el artefacto debe ser el que se despliega.
- Verificación: el proceso de arranque no invoca `tsx`/`ts-node` sobre `src/`.

## R3 — Rate limiting distribuido, nunca `Map` en memoria

- Prohibido `new Map()` como almacén de rate limiting en producción.
- Usar Redis/Upstash/Postgres con operación atómica y TTL; si el almacén falla, fallar cerrado.
- Verificación: `grep -rn "new Map" --include=*.ts | grep -i "rate\|limit"` no debe devolver almacenes en memoria.

## R4 — Barrera de secretos sobre artefactos publicados

- Antes de publicar, ejecutar `grep`/gitleaks sobre `dist/`, `_site/`, `site-dist/` y cualquier carpeta servida.
- Un hallazgo bloquea el despliegue; no se publica con excepciones sin revisión de `@belentani7`.

## R5 — `.gitleaks.toml` protegido

- `CODEOWNERS` debe exigir revisión de `@belentani7` para `.gitleaks.toml` y `.github/`.
- Cambiar la configuración de secretos requiere PR separado y justificación.

## R6 — Validación de entrada y cabeceras

- Validar toda entrada externa con esquema (Zod, Pydantic o equivalente).
- Cabeceras mínimas: `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`.
- Cookies de sesión: `HttpOnly`, `Secure`, `SameSite=Lax` o más estricto.

## R7 — Cadena de suministro

- Lockfile versionado y usado en CI (`npm ci`, `pnpm install --frozen-lockfile`, `pip install -r ...`).
- Dependabot activo; `npm audit --omit=dev --audit-level=high` sin hallazgos altos abiertos.
- Prohibido `latest` en dependencias de producción.

## R8 — Revisión y protección de rama

- Mínimo 2 reviewers; commits firmados; CI verde; branch protection en `main`.
- El PR debe completar la checklist y declarar el impacto de seguridad.
- Sin excepciones documentadas no hay merge.

## Checklist de PR

- [ ] R1 sin secretos (gitleaks limpio)
- [ ] R2 artefacto compilado verificado
- [ ] R3 rate limiting distribuido
- [ ] R4 barrera sobre artefactos
- [ ] R5 CODEOWNERS correcto
- [ ] R6 validación y cabeceras
- [ ] R7 lockfile y auditoría de dependencias
- [ ] R8 dos reviewers y CI verde
