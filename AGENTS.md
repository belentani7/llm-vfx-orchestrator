# llm-vfx-orchestrator — AGENTS.md

> Repositorio del ecosistema belentani7. Adaptado automáticamente con superpowers + impeccable.

## Contexto del proyecto

Repositorio clonado de GitHub (belentani7/llm-vfx-orchestrator). Tecnología detectada: nodejs, react, vite, typescript, python, has-security-md, has-html.

## Reglas de desarrollo

### Protocolo spec-first

Toda modificación sigue: PRD → SRS → Design Doc → ADR → Plan → Tests GWT.

### Impeccable (diseño frontend)

Registro brand y product. Pre-ship checklist obligatoria:
- Body text contrast >= 4.5:1
- No muted gray on tinted backgrounds
- Line length capped at 65-75ch
- Display letter-spacing >= -0.04em
- No gradient text
- No side-stripe borders
- No eyebrow on every section
- No identical card grids
- No nested cards
- z-index semántico, nunca 999/9999
- Animaciones con prefers-reduced-motion
- No bounce ni elastic easing
- Touch targets >= 44px
- Estados vacío, error y carga diseñados

### Tokens de diseño (CANON)

- Negro vacío: #05030a
- Rojo neón: #ff073a
- Dorado Zion: #d4af37
- Cyan señal: #4de8e0

## Seguridad

- No commitear secretos, API keys, tokens ni credenciales.
- Ejecutar gitleaks antes de cada push.
- CODEOWNERS: @belentani7 revisión requerida.

## Comandos

- Despliegue: copiar archivos (cero build) salvo que el repo tenga package.json o equivalent.

## Convenciones de commit

`type(scope): summary` (feat, fix, docs, chore, refactor, test, perf, style).

<!-- repo-forge:agents:inicio -->
# AGENTS.md — instrucciones para agentes

Cualquier agente que toque **LLM VFX Orchestrator** debe:

1. Leer `BIBLIA.md` y `plataforma/FICHA.md` antes de escribir.
2. Ejecutar `python scripts/doctor.py` al empezar y al terminar.
3. Respetar el techo de alcance: no añadir módulos que la ficha no describa.
4. No borrar archivos, no reescribir historia, no hacer push sin pedido explícito.
5. Declarar en el informe qué se ejecutó y qué no; lo no ejecutado no se afirma.

## Comandos seguros

| Comando | Efecto |
|---|---|
| `python scripts/doctor.py` | Solo lectura; devuelve el estado de reglas |
| `python -m unittest discover -s tests` | Pruebas locales |

<!-- repo-forge:agents -->
<!-- repo-forge:agents:fin -->
