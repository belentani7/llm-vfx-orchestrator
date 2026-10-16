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