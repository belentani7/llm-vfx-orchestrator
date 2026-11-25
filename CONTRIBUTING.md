# Guía de contribución — LLM VFX Orchestrator

Gracias por contribuir a **LLM VFX Orchestrator**, parte del ecosistema Belentani.

## Requisitos del entorno

- **Python**: `>= 3.11` (`pip install -e ".[dev]"`)
- **Node.js**: `22.x` (`npm ci` o `pnpm install --frozen-lockfile`)

## Flujo de trabajo

1. Lee `BIBLIA.md`, `AGENTS.md` y `plataforma/FICHA.md` antes de proponer cambios de alcance.
2. Ejecuta `python3 scripts/doctor.py` para comprobar la integridad estructural del repositorio.
3. Implementa cambios atómicos siguiendo el protocolo spec-first (requisito → diseño → cambio mínimo → test verificable).
4. Nunca incluyas claves API, tokens, endpoints privados ni datos sensibles en código, tests o manifiestos.

## Verificación obligatoria antes de abrir un Pull Request

```bash
# Gobernanza y catálogo
python3 scripts/doctor.py
node scripts/validate-catalog.mjs

# Pipeline Python
ruff check .
pytest -q tests

# Workspace Web (TypeScript + Lint + Tests + Build + Auditoría)
npm run check
npm run lint
npm test
npm run build
npm run audit:web
```

## Convención de commits

Usa Conventional Commits en minúsculas:

- `feat(scope): descripción breve`
- `fix(scope): corrección verificada`
- `perf(scope): mejora medible de rendimiento`
- `test(scope): cobertura unitaria o E2E`
- `docs(scope): documentación técnica`
- `chore(scope): mantenimiento y herramientas`
