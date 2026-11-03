# llm-vfx-orchestrator — BIBLIA.md

> Documento de doctrina del producto. Visión, misión, reglas, arquitectura, stack y decisiones de diseño.

## 1. Visión

llm-vfx-orchestrator es un producto del ecosistema belentani7. 
Forma parte del universo integrado de proyectos bajo la organización GitHub belentani7.

## 2. Misión

Proveer valor a través de tecnología moderna, código mantenible y experiencia de usuario excepcional.

## 3. Stack Tecnológico

- **Node.js**: Runtime principal
- **React**: Interfaz de usuario
- **TypeScript**: Tipado estático
- **Python**: Backend y scripts
- **Vite**: Build tool y dev server

## 4. Reglas de Desarrollo

- Protocolo spec-first: PRD → SRS → Design Doc → ADR → Plan → Tests GWT
- No commitear secretos, API keys, tokens ni credenciales
- Ejecutar gitleaks antes de cada push
- CODEOWNERS: @belentani7 revisión requerida
- Conventional commits: type(scope): summary
- Cada cambio es reversible, uno a uno

## 5. Tokens de Diseño (CANON)

- Negro vacío: #05030a (body bg)
- Rojo neón: #ff073a (acento primario)
- Dorado Zion: #d4af37 (acento secundario)
- Cyan señal: #4de8e0 (acento terciario)

## 6. Impeccable (Diseño Frontend)

- Body text contrast >= 4.5:1
- No gradient text, no side-stripe borders, no eyebrow on every section
- No identical card grids, no nested cards
- Hero heading <= 6rem (96px)
- Touch targets >= 44px, focus indicators visible
- Estados vacío, error y carga diseñados
- Animaciones con prefers-reduced-motion

## 7. Seguridad

- .gitleaks.toml configurado con reglas del ecosistema Belentani
- CODEOWNERS @belentani7
- SECURITY.md con política de reporte

## 8. Decisiones de Arquitectura

- Monorepo o repositorio independiente según el producto
- Despliegue por copia de archivos (cero build) salvo que se especifique lo contrario
- Working trees respetados: no se sobrescriben cambios sin restaurar desde HEAD
