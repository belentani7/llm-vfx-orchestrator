# llm-vfx-orchestrator

Autonomous VFX pipeline orchestration using LLMs (Claude, Qwen-VL, GLM) connected to ComfyUI APIs.
The pipeline plans a render, watches it, inspects the *actual pixels*, and corrects itself until the
quality threshold is met — or escalates for human review instead of burning GPU time.

## Architecture

```
DirectorAgent (Claude)      ->  workflow planning, JSON generation        (vision: no)
AssetManagerAgent (GLM)     ->  LoRA/model/texture lookup (optional)      (vision: no)
QAInspectorAgent (Qwen-VL)  ->  visual quality assessment of the render   (vision: yes)
CorrectionAgent (Claude)    ->  surgical patch of the failing graph       (vision: no)
        |
  ComfyUI API (queue / websocket / history / view)
        |
  Closed loop: render -> QA -> patch -> re-render  ->  completed | escalated | failed
        |
  JobStore (atomic JSON per job) -> vfp status / vfp jobs / vfp retry
```

See [`AUDITORIA.md`](AUDITORIA.md) for the full technical audit: 25 findings with reproducible
evidence, what was fixed, and the capacity numbers.

## Installation

**Instalación reproducible desde el código fuente** (no se presupone una publicación en PyPI):

```bash
git clone https://github.com/belentani7/llm-vfx-orchestrator.git
cd llm-vfx-orchestrator
python -m pip install -e ".[dev]"
cp config.example.yaml config.yaml  # PowerShell: Copy-Item config.example.yaml config.yaml
```

No incluyas secretos en `config.yaml` ni en el repositorio; exporta `ANTHROPIC_API_KEY` y `DASHSCOPE_API_KEY` en el entorno seguro antes de ejecutar el pipeline. El archivo `config.yaml` se excluye del control de versiones.

### Requirements

- Python 3.11+
- A running ComfyUI instance (default: `http://127.0.0.1:8188`)
- API keys for at least one LLM provider (env vars or config YAML)

## Quick Start

La [página de producto](docs/index.html) describe arquitectura y operación; es documentación estática, **no** un renderizador en el navegador. Se necesita acceso al repositorio, a ComfyUI y a los servicios LLM configurados. 

```bash
# 0. Verify config, ComfyUI, providers and store
vfp doctor -c config.yaml

# 1. Plan only (no render) and inspect the graph the Director produced
vfp plan --prompt "cyberpunk alley at night, rain" --template environment_generation -o workflow.json

# 2. Render an existing workflow
vfp run workflow.json -c config.yaml

# 3. Or let the Director plan and render in one shot
vfp run --prompt "hero portrait, rim light" --template character_generation

# 4. Batch with concurrency (capacity: -j / pipeline.concurrency)
vfp run --batch jobs.json -j 8 -c config.yaml

# 5. Inspect results
vfp jobs
vfp status <job_id> --json
vfp retry <job_id>            # re-runs the stored graph under the current config
```

Exit code is `0` only when every job ends `completed`; `failed` and `escalated` return `1`, so the CLI
drops straight into CI/cron.

## Configuration

```yaml
comfyui:
  host: "127.0.0.1"
  port: 8188
  timeout: 300
  ws_timeout: 3600            # hard deadline waiting for one render
  max_concurrent_renders: 1   # raise on multi-GPU / beefy servers
  use_proxy: false            # never route local traffic through HTTP_PROXY
#  api_url: "https://comfy.example.com"   # remote/behind reverse proxy (wins over host/port)

llm:
  claude:
    model: "claude-sonnet-4-20250514"
    api_key: "${ANTHROPIC_API_KEY}"
  qwen:
    model: "qwen-vl-max"
    api_key: "${DASHSCOPE_API_KEY}"
    vision: true              # this provider receives the rendered pixels
  glm:
    model: "glm-4v-plus"
    api_key: "${ZHIPUAI_API_KEY}"
  fallbacks: [glm, qwen]      # used when the role's provider errors out
#  providers:                # any OpenAI-compatible endpoint (Ollama, vLLM, Groq, Gemini…)
#    local:
#      model: "qwen2.5-vl"
#      base_url: "http://127.0.0.1:11434"
#      kind: openai

pipeline:
  max_retries: 3              # correction retries
  qa_threshold: 0.8
  min_score_improvement: 0.01 # below this, the loop is considered stalled
  plateau_patience: 2         # stalled attempts before escalating
  concurrency: 4              # jobs run in parallel (vfp run -j)
  qa_concurrency: 4           # QA fan-out per job
  max_qa_images: 4            # images inspected per render
  correct_execution_errors: true   # try to fix ComfyUI execution errors (OOM, bad node…)
  store_dir: ""               # default ~/.vfp/jobs (or $VFP_HOME)

template:
  name: character_generation
  use_assets: false
```

Environment overrides: `VFP_MAX_RETRIES`, `VFP_QA_THRESHOLD`, `VFP_CONCURRENCY`, `VFP_QA_CONCURRENCY`,
`VFP_STORE_DIR`, `VFP_COMFYUI_URL`, `VFP_COMFYUI_HOST`, `VFP_COMFYUI_PORT`, `VFP_COMFYUI_TIMEOUT`,
`VFP_COMFYUI_WS_TIMEOUT`, `VFP_COMFYUI_CONCURRENCY`, `VFP_HOME`.
Anything else can be overridden per run: `vfp run wf.json --set pipeline.qa_threshold=0.9`.

## Pipeline Templates

Pre-built templates in `orchestrator/templates/` (also usable from the CLI with `--template`):

| Template | Description |
|---|---|
| `character_generation.yaml` | Character art with style LoRAs |
| `environment_generation.yaml` | Environment / scene generation |
| `product_render.yaml` | Product photography renders |

Templates only fill values the Director left empty, so an explicit workflow always wins.

## How the Feedback Loop Works

1. **Director** generates a ComfyUI workflow JSON from the prompt (+ template + asset hints)
2. **ComfyUI** executes the render; the client follows queue + websocket with a hard deadline and a
   `/history` fallback if the socket drops
3. **QA Inspector** receives the rendered image (base64) and returns a normalized score/issues
4. If quality is below threshold, the **Correction Agent** patches the graph (inputs, add/remove nodes)
5. Steps 2-4 repeat up to `max_retries`; the loop stops early on a plateau or a no-op patch
6. Jobs end **completed**, **escalated** (human review, `escalation_reason` persisted) or **failed**

## Testing

- `pytest -q` runs the whole suite offline.
- `tests/test_integration_smoke.py` starts a real HTTP + websocket ComfyUI stand-in on localhost and runs
  the pipeline end to end with the production client (queue → WS terminal event → `/view` download → vision QA → store).

## Capacity

- `vfp run --batch jobs.json -j N` runs independent jobs concurrently (bounded by `comfyui.max_concurrent_renders`).
- QA of the rendered images runs in parallel per job (bounded provider concurrency, pooled HTTP clients).
- `llm.fallbacks` keeps the pipeline alive when a provider degrades.
- Measure it yourself, no GPU needed:

```bash
python scripts/benchmark.py --jobs 24 --render-ms 50 --qa-ms 20 --images 2 --concurrency 1,2,4,8
```

## Development

```bash
pip install -e ".[dev]"
pytest -q          # offline regressions, no network required
ruff check .
python scripts/benchmark.py
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
