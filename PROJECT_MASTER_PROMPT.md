# PROJECT_MASTER_PROMPT — LLM VFX Orchestrator — dirección y orquestación de efectos visuales

**Documento canónico de intención y dirección de producto** · 22/10/2026  
**Repositorio:** `belentani7/llm-vfx-orchestrator`  
**Regla de lectura:** hechos observados separados de propuestas; este archivo no sustituye el README técnico ni las reglas preexistentes del repositorio.

## 1. ADN del proyecto — qué es y qué no es

- **Producto**: pipeline técnico para orquestar tareas VFX con agentes LLM y ComfyUI; no una landing falsa que promete renderizar sin motor.
- **Runtime verificado por manifiestos**: Python >=3.11, `orchestrator/` con `pipeline.py`, `llm_agents.py`, `comfyui_client.py`, `feedback_loop.py`, `state.py`, `store.py`, `cli.py`; `pyproject.toml` declara comando `vfp`.
- **Interfaz separada**: React/Vite/TypeScript en `package.json`; recursos narrativos/visuales en `magic/`. El README actual es mínimo y no demuestra el funcionamiento.
- **Identidad**: estudio de dirección creativa con control profesional de reproducibilidad y coste.

## 2. Norte creativo y tecnológico: máximo potencial

Evolucionar hacia un **estudio VFX orquestado de principio a fin**: brief → descomposición por planos → guion visual → workflow ComfyUI validado → ejecución controlada → revisión de calidad → entrega rastreable, siempre diferenciando simulación y render real.

## 3. Producto ideal y recorrido de usuario

- Ingreso de brief, referencias con derechos declarados, ratio, duración, FPS, semillas, estilo e intención narrativa.
- Panel de proyecto y shot list con estados honestos (preparado, en cola, procesando, revisión, fallido, entregado); visualización de dependencia y progreso si hay motor.
- Versiones de prompts y configuraciones, historial de artefactos, reintentos idempotentes, vistas previa y comparación de iteraciones, descarga con manifiesto de procedencia.
- Control de presupuestos de GPU/proveedor, límites por usuario e indicación explícita de servicios no configurados.

## 4. Arquitectura y diseño técnico para llegar allí

- Python orquestador como núcleo: adaptadores LLM y ComfyUI tras interfaces claras, trabajos persistentes e identificadores estables, validación de workflows con esquemas.
- Revisar `orchestrator/state.py`, `store.py` y `pipeline.py` antes de cambiar persistencia; conservar recuperabilidad de jobs, idempotencia y trazabilidad.
- Frontend de operación, no solo una página visual. API tipada para jobs, artefactos, registros, reintentos y cancelación; autenticación y cuota antes de multiusuario.
- `magic/` queda como laboratorio creativo, no debe corromper el motor productivo.

## 5. Plan de construcción por resultados observables

1. Reproducir CLI `vfp`, `pytest` y `ruff` donde existan; trazar pipeline real de extremo a extremo sobre un fixture seguro.
2. Completar contratos de job/estado, manejo de errores de red y fallo de ComfyUI, timeouts, backoff y reintentos seguros.
3. Añadir modo local demostrable sin gastar GPU ni crédito y modo remoto auténtico con secretos de servidor.
4. Integrar panel de planos y entregables con UX de producción; adjuntar pruebas de contratos y estados de error.
5. Instrumentar costes, latencias, cancelaciones y trazabilidad de modelos/semillas como metadatos, no métricas ficticias.

## 6. Límites innegociables de este producto

No se pueden prometer generaciones sin ComfyUI operativo o proveedor conectado. No se deben subir credenciales, materiales privados, rostros o audios de terceros sin derechos. La estética de `magic/` no sustituye la funcionalidad.


## Protocolo obligatorio para el siguiente agente (ejecución, no relato)

> **Instrucción operativa**: Recupera primero la realidad del repositorio y eleva ESTE producto a su máximo potencial sin cambiar su identidad. Este archivo es el canon estratégico y un prompt reutilizable; **no es prueba** de que las funciones aquí propuestas ya existan.

1. Lee `README.md`, directorios de código, configuración, documentación y pruebas. Contrasta el árbol y el código actual con lo declarado aquí. Marca cada capacidad como existente, parcial o futura; nunca presentes ideas como funciones terminadas.
2. Respeta la intención original, licencia, titulares de derechos, público y estilo visual. No crees otro repositorio, una copia sin motivo, un fork de producto ni mezcles productos independientes.
3. Construye verticalmente: cada entrega debe comprender experiencia de usuario, lógica, contenido y persistencia/integraciones reales **solo cuando sean necesarias**, así como control de errores, accesibilidad, seguridad y pruebas. Nunca simules bases de datos, métricas, usuarios ni integraciones.
4. Antes de adoptar proveedor, framework o infraestructura nueva, demuestra la necesidad y el coste de mantenerla. Prefiere las dependencias existentes, contratos estables y componentes reutilizables; ninguna clave de API va al frontend o al repositorio.
5. No borres material histórico o creativo ni modifiques datos personales, secretos, dominios, estado público/privado o despliegues irreversibles sin respaldo y autorización específica. No sustituyas contenido auténtico por texto de relleno.
6. Cambios pequeños y trazables, con pruebas, lint, build y validación manual de los flujos esenciales; documenta la diferencia exacta entre **implementado**, **validado** y **pendiente**.
7. Si un objetivo se opone al valor central de este proyecto, prioriza su identidad sobre la homogeneización del ecosistema. Los vínculos con otros proyectos son integraciones opcionales, no órdenes de fusión.

## Definición de terminado

Un incremento está terminado solo cuando el usuario alcanza el objetivo principal sin pantallas vacías ni navegación rota; el contenido es auténtico y mantenible; el estado de datos es consistente; errores y límites de uso son legibles; privacidad/accesibilidad/seguridad están contempladas; hay pruebas reproducibles y el despliegue, si se anuncia, ha sido comprobado en su URL real. Cada afirmación pública debe estar sustentada por código, datos o evidencia actual.

## Prompt maestro reutilizable

«Actúa simultáneamente como responsable de producto, director de arte, arquitecto de software, desarrollador full-stack, especialista en contenido, accesibilidad y seguridad de **este repositorio**. Relee este canon y el código real antes de intervenir. Detecta la diferencia entre el producto actual y su visión máxima. Elige el siguiente incremento más valioso para el usuario final, constrúyelo de extremo a extremo sobre la estructura existente, prueba lo que afirmas y documenta resultados comprobados y limitaciones. Mantén identidad, trazabilidad y autonomía del proyecto. No conviertas esta visión en otra auditoría sin cambios ni en un rediseño genérico». 
