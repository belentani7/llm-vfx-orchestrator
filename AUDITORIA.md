# Auditoría técnica de `llm-vfx-orchestrator`

**Alcance:** commit base `8fb07b2` → versión corregida `0.2.0` (rama `arena/5a822cf2-llm-vfx-orchestrator`).
**Método:** lectura del código + **reproducción real de cada fallo** ejecutando el código antiguo en un
entorno aislado (`git archive HEAD` → `/tmp/old`, venv limpio) + verificación de la corrección con
**262 tests** (eran 24) y `ruff check` limpio.

> Las 24 pruebas originales pasaban en verde porque mockeaban `_call_llm` y el cliente de ComfyUI con
> `AsyncMock`: los mocks devolvían exactamente la forma que el código esperaba, así que ninguno de los
> fallos de integración 1–6 podía detectarse. La corrección incluye pruebas que ejercitan el HTTP real
> (`httpx.MockTransport`), el protocolo websocket (socket falso) y el bucle completo render→QA→corrección.

---

## 1. Resumen ejecutivo

| Área | Antes | Después |
|---|---|---|
| Bucle de corrección | `execute()` terminaba en `correcting` y nunca re-renderizaba | Bucle cerrado render→QA→parche→re-render con presupuesto de reintentos |
| QA visual | El inspector solo recibía `"nombre (N bytes)"` | La imagen (PNG) viaja en base64 al proveedor de visión |
| Qwen/DashScope | `KeyError: 'choices'` (protocolo incorrecto) | Endpoint multimodal nativo + parser `output.choices[]` + modo compatible OpenAI |
| Estado entre procesos | `vfp status`/`vfp retry` inservibles (estado en RAM) | `JobStore` en disco (atómico), `vfp jobs`, `vfp retry` real |
| Websocket | No reconocía el final del render; reabría el socket y reprocesaba el guion | Eventos terminales + deadline + *fallback* a `/history` |
| Resiliencia LLM | Sin reintentos; un 429/503 mataba el job | 3 reintentos con backoff+jitter, `Retry-After`, cadena de *fallbacks* |
| Configuración | Cualquier clave extra provocaba `TypeError`; `template:` se ignoraba | Carga tolerante con avisos, `--set`, `VFP_*`, templates aplicables |
| Capacidad | 1 job en serie, QA secuencial, un cliente HTTP por llamada | Batch concurrente, QA en paralelo, *pool* de conexiones, semáforos por proveedor |
| Calidad | 24 tests, sin CI, `pydantic` sin usar | 262 tests (incluye integración con HTTP+WS reales), CI 3.11/3.12, ruff, `benchmark.py`, `vfp doctor` |

**Capacidad medida** (`python scripts/benchmark.py --jobs 24 --render-ms 50 --qa-ms 20 --images 2`):
24 jobs simulados, concurrencia 1→8: **10.4 → 96 jobs/s (9.2×)**, con `peak render` = concurrencia
solicitada y QA en paralelo por job.

---

## 2. Hallazgos y evidencias

### Críticos

| # | Hallazgo | Evidencia (código original) | Corrección | Tests |
|---|---|---|---|---|
| 1 | **La QA no veía la imagen.** `QAInspectorAgent.inspect(image_description, criteria)`; el pipeline enviaba `f"Rendered image: {name} ({len(bytes)} bytes)"`. El "juicio visual" era una invención del LLM sobre un nombre de fichero. | firma de `inspect` y de `_call_llm` (sin parámetro `image`) | `_call_llm(..., image=..., image_media_type=...)` construye payload multimodál (anthropic base64, openai `image_url`, dashscope `image`); el pipeline descarga el render y lo adjunta | `test_pixels_are_sent_to_the_inspector`, `test_anthropic_happy_path`, `test_openai_payload_with_image`, `test_dashscope_payload_with_image` |
| 2 | **Qwen/DashScope inoperante**: se enviaba `{model, max_tokens, messages}` y se leían `choices` de la raíz, pero el endpoint nativo exige `input.messages` y responde `output.choices[].message.content`. | `FALLO -> KeyError: 'choices'` al llamar `_call_llm` con una respuesta DashScope real | `resolve_endpoint`/`build_payload`/`parse_response` por protocolo (`anthropic`/`dashscope`/`openai`), autodetectado y sobreescribible con `kind` | `TestProtocolDetection`, `test_dashscope_happy_path` |
| 3 | **El bucle de corrección no existía.** `execute()` acababa en `PipelineState.CORRECTING` y retornaba; el CLI nunca llamaba a `retry_with_corrections`, así que "autonomous correction" no ocurría nunca. | `orchestrator/pipeline.py` (código original): `sm.transition(CORRECTING…)` como último paso | `_run()` implementa el bucle completo con presupuesto (`max_retries`), detección de *plateau* y escalado | `test_completes_after_correction`, `test_escalates_when_retries_exhausted`, `test_escalates_on_plateau` |
| 4 | **La corrección era a ciegas:** `FeedbackLoop.analyze_failure` llamaba al agente con `workflow={}`, por lo que los parches se generaban sin conocer el grafo. | `feedback_loop.py` original: `patch = await self._agent.generate_fix(workflow={}, …)` | se pasa el workflow real, el log de error y los intentos previos ("no repitas") | `test_completion_receives_prior_attempts`, `test_correction_receives_prior_attempts`, `test_correction_agent_generate_fix` |
| 5 | **`vfp status`/`vfp retry` inservibles.** El estado vivía en `self._state` (memoria del proceso) y `retry` solo imprimía "(Retry requires the original workflow…)". | proceso 1: `JOB=eb672bc2 STATUS=completed` → proceso 2: `vfp status eb672bc2 → exit=1: Job eb672bc2 not found` | `JobStore` (JSON atómico por job, workflow+prompt+métricas), `vfp jobs`, `vfp retry` que reejecuta el grafo guardado; `get_status` consulta memoria y disco | `test_job_is_persisted_and_readable`, `test_status_is_readable_from_another_process`, `test_retry_uses_the_stored_workflow`, `TestRetry` (CLI) |
| 6 | **El websocket no reconocía el final.** Solo cortaba en `executed`/`execution_error`, así que ante `execution_success` (protocolo actual) reabría el socket y volvía a leer el mismo guion hasta agotar los 5 intentos: renders "eternos" y eventos duplicados. | mensajes consumidos: `['execution_success','progress', … ] ×5`, `conexiones websocket abiertas: 5` | `TERMINAL_MESSAGE_TYPES` (`execution_success/error/interrupted/cancelled`), `executing` con `node: null`, deadline único y *fallback* a `/history` | `test_monitor_stops_on_execution_success`, `TestWaitForPrompt` (6 casos) |

### Altos

| # | Hallazgo | Corrección | Tests |
|---|---|---|---|
| 7 | Sin timeout en la espera del render: un job colgado bloqueaba el pipeline indefinidamente. | `comfyui.ws_timeout` (3600 s) con deadline compartido entre reconexiones; al expirar se llama a `/interrupt` para no dejar trabajo en la GPU | `test_timeout_interrupts_the_queued_render` |
| 8 | Sin reintentos en las llamadas LLM: un 429/503 puntual (habitual en DashScope/Zhipu) abortaba QA o planificación. | `LLMProviderConfig.max_retries` + backoff exponencial con jitter + respeto de `Retry-After`; 4xx de cliente no se reintentan | `test_retries_on_429_honoring_retry_after`, `test_retries_on_5xx_with_backoff`, `test_client_error_is_not_retried` |
| 9 | `from_yaml` estricto: cualquier clave extra reventaba (`ComfyUIConfig.__init__() got an unexpected keyword argument 'api_url'`), y las claves planas de `pipeline:` se ignoraban. | Carga tolerante por tipo con `get_type_hints`, coerción de escalares, avisos por claves desconocidas, soporte de `pipeline:` y forma plana | `TestFromYaml` (7 casos) |
| 10 | La sección `template:` del YAML se descartaba: los templates del README no tenían efecto. | `orchestrator/template.py` (`load_template`, `apply_template_defaults`) + `--template` en CLI, con relleno solo de valores ausentes | `TestTemplates`, `test_execute_prompt_applies_template_defaults` |
| 11 | `download_image` ignoraba `subfolder`/`type` → 404 con `SaveImage` que usa subcarpetas. | `OutputImage(filename, subfolder, type, node_id)` + `download_image` con parámetros correctos y reintentos | `test_download_image_uses_subfolder_and_type`, `test_get_output_images_collects_files_and_metadata` |
| 12 | Puntuaciones sin normalizar: `"0.85"` rompía la comparación, `"85%"` o `9` colaban cualquier umbral. | `coerce_score` (0-1, %, x/10) y `normalize_qa_report` (issues alternativas, extras preservados) | `TestCoerceScore`, `TestNormalizeQaReport` |
| 13 | Respuestas LLM con ```json, prosa alrededor o comas finales → `json.loads` lanzaba y el job fallaba. | `extract_json` (fences, extracción por paréntesis balanceados, reparaciones) + reintento de "reparación" en `_call_json` | `TestExtractJson` (7 casos), `test_json_repair_retry` |
| 14 | `ws_reconnect_attempts: 0` ⇒ generador vacío ⇒ el pipeline creía que el render había terminado sin outputs. | el valor se acota a ≥ 1 | `test_clamps_concurrency` |
| 15 | Un fallo de QA o de descarga se interpretaba como "calidad 0" ⇒ se corregía un render que quizá estaba bien. | informes marcados `degraded`; si **todos** fallan, se escala a revisión manual en vez de gastar GPU | `test_qa_outage_escalates_instead_of_rerendering`, `test_download_failure_escalates` |
| 16 | Parche vacío ⇒ re-render idéntico (gasto de GPU y API sin cambio). | si el parche no modifica el grafo se escala con motivo explícito | `test_empty_patch_escalates_instead_of_rerendering` |

### Medios

| # | Hallazgo | Corrección |
|---|---|---|
| 17 | `httpx.AsyncClient` nuevo en cada llamada LLM (TLS/handshake por petición). | pool compartido por (timeout, proxy) con límites de conexiones. |
| 18 | Sin tope de concurrencia por proveedor. | semáforo por `(endpoint, modelo)` con `max_concurrency` (test `test_provider_concurrency_is_capped`). |
| 19 | El README documenta escalado a revisión manual, pero el state machine no tenía estado `ESCALATED`. | estado `ESCALATED` + transiciones y `history_dicts()` para persistir. |
| 20 | `pydantic>=2.0` como dependencia de runtime sin usarse. | eliminada de `pyproject.toml`. |
| 21 | `orchestrator/` sin `__init__.py` (namespace implícito): sin `__version__` ni metadatos fiables. | `__init__.py` con `__version__` y `vfp --version`. |
| 22 | Sin CI. | `.github/workflows/ci.yml`: ruff + pytest en 3.11/3.12. |
| 23 | README documentaba comandos inexistentes (`vfp run`, `vfp retry` "reales"). | README reescrito con CLI, config y configuración de capacidad. |
| 24 | Fallos de configuración se descubrían a mitad del job. | `vfp doctor`: comprueba ComfyUI (`/system_stats`, VRAM), proveedores, store y templates, con `--json` y exit code. |
| 25 | `HTTP_PROXY`/`HTTPS_PROXY` del entorno podían secuestrar el tráfico al ComfyUI local. | `comfyui.use_proxy: false` por defecto (`trust_env=False`, `proxy=None` en WS) y `follow_redirects` para despliegues tras reverse-proxy; `llm.*.use_proxy: true` por defecto. |

---

## 3. Cambios de API (posible impacto para integradores)

| Antes | Ahora |
|---|---|
| `llm_agents._resolve_api(provider) -> (url, headers)` | `resolve_endpoint(provider) -> ProviderEndpoint(url, headers, kind, model, trust_env)` + `detect_kind` |
| `_call_llm(provider, system, user, max_tokens=4096)` | `_call_llm(..., *, image=None, image_media_type="image/png", client=None)` |
| `QAInspectorAgent.inspect(description, criteria)` | `inspect(description, criteria, *, image=…, extra_context=…)` (compatible hacia atrás en los dos primeros parámetros) |
| `ComfyUIClient.get_output_images() -> list[str]` | `list[OutputImage]` (usa `image_name()`/`str()` para obtener el nombre) |
| `ComfyUIClient.websocket_monitor()` (sin final) | terminal + `wait_for_prompt() -> RenderOutcome` |
| `VFPPipeline.execute()` terminaba en `correcting` | `execute()` completo; `retry_with_corrections()` se mantiene como *shim* compatible |
| — | Nuevos: `plan_prompt`, `run_batch`, `run_retry`, `list_jobs`, `get_job`, `close`/`__aenter__` |
| — | Nuevos módulos: `utils`, `store`, `template`; `store_dir`, `concurrency`, `qa_concurrency`, `min_score_improvement`, `plateau_patience`, `vision_max_bytes`, `correct_execution_errors` en config |

---

## 4. Capacidad: qué se ganó y cómo medirlo

1. **Batch concurrente**: `vfp run --batch jobs.json -j 8` o `pipeline.run_batch([...], concurrency=8)`,
   con semáforo que respeta `comfyui.max_concurrent_renders` (la GPU no se satura de cola).
2. **QA en paralelo** por job (`qa_concurrency`, `max_qa_images`) y QA multimodal real.
3. **Cadena de proveedores**: `llm.fallbacks: [glm, qwen]` permite sobrevivir a la caída de un proveedor;
   `llm.providers.<nombre>` admite cualquier endpoint compatible con OpenAI (Ollama/vLLM incluidos).
4. **Menos gasto inútil**: plateau, parches vacíos, QA caída y timeouts cortan el bucle en lugar de
   quemar GPU/API; los reintentos con backoff evitan abortos por un 429 puntual.
5. **Observabilidad**: métricas por job (`renders`, `total_render_s`, `total_qa_s`, `total_correction_s`,
   `total_s`, `worst_score`), historial de transiciones persistido y `vfp jobs`/`vfp status --json`.
6. **Benchmark reproducible**: `python scripts/benchmark.py` (sin GPU ni red). Resultado de referencia:
   `conc=1 → 10.4 jobs/s`, `conc=8 → 96 jobs/s (9.2×)`, `peak render` = concurrencia solicitada.

---

## 5. Verificación

```bash
pip install -e ".[dev]"
pytest -q                     # 262 passed
ruff check .                  # All checks passed
python scripts/benchmark.py   # tabla de capacidad simulada
vfp doctor -c config.yaml     # ComfyUI, proveedores, store y templates
vfp run --prompt "cyberpunk alley, rain" -j 4
vfp jobs && vfp status <job_id> && vfp retry <job_id>
```

## 6. Límites de esta auditoría (honestidad sobre lo no verificado)

- **No se ha ejecutado contra un ComfyUI real con GPU ni contra las APIs de LLM reales** en este entorno
  (sin GPU ni claves). Lo que sí está verificado de punta a punta es el **protocolo**: `tests/test_integration_smoke.py`
  levanta un servidor HTTP real (`/prompt`, `/history/{id}`, `/view`, `/system_stats`) y un servidor
  websocket real en localhost, y ejecuta el pipeline completo con el cliente real (sin mocks de red):
  encolado, eventos WS hasta `execution_success`, descarga del PNG (verificando `filename`, `subfolder`
  y `type`), envío de los píxeles al modelo de visión y persistencia del job. Aun así, conviene un
  *smoke test* contra el servidor de producción antes de desplegar: `vfp doctor -c config.yaml` y un
  `vfp run` con un workflow trivial (`KSampler` 8 steps, 256x256) son el camino más corto.
- `QAInspectorAgent` sigue prefiriendo Qwen-VL; proveedores sin visión (`vision: false`) reciben solo
  texto y el informe se marca como adjunto ausente.
- El escalado (`ESCALATED`) no notifica a nadie: la integración con Slack/webhook queda como trabajo
  futuro (el store ya guarda `escalation_reason` para engancharlo).
