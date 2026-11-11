# Contributing to Belentani Project

## Getting Started

1. Fork the repository and clone it locally
2. Install dependencies: `npm install` or `pip install -r requirements.txt`
3. Create a branch: `git checkout -b feat/feature-name`

## Development Workflow

- Run linting: `npm run lint` or `python -m ruff lint`
- Run tests: `npm test` or `python -m pytest`
- Build the project: `npm run build` or `pip install -e .`

## Pull Request Process

1. Commit your changes using conventional commits: `git commit -m "feat: add new feature"`
2. Push to your fork: `git push origin feat/feature-name`
3. Submit a Pull Request with a clear description
4. Link any related issues: `Fixes #123`

## Code Standards

- Follow the project's code style (ESLint/Prettier for JS, ruff/black for Python)
- Write tests for new functionality
- Update documentation as needed
- Ensure all CI checks pass before merging

## Reporting Issues

- Use the issue templates: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Check for existing issues first
- Provide clear reproduction steps
- Include environment details (OS, version, etc.)

<!-- repo-forge:contributing:inicio -->
# Contribuir

## Antes de tocar nada

1. Lee `BIBLIA.md` (doctrina del repositorio) y `plataforma/FICHA.md` (alcance permitido).
2. Ejecuta `python scripts/doctor.py` y guarda la salida: es la línea base.
3. Un cambio resuelve **un solo resultado verificable**.

## Cómo enviar

```bash
git checkout -b fix/<asunto-corto>
# ... cambio mínimo ...
python scripts/doctor.py
git commit -m "fix(alcance): <qué se arregla>"
```

Convención de commit: `type(scope): resumen` con tipos `feat|fix|docs|chore|refactor|test|perf`.

## Qué no se acepta

- Cambios que rompan una regla del catálogo sin justificar la excepción.
- Archivos generados a mano que el build regenera.
- Datos personales, credenciales o capturas de clientes.
- Promesas en el README que el código no cumpla.

<!-- repo-forge:contributing -->
<!-- repo-forge:contributing:fin -->
