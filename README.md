# LLM VFX Orchestrator

A two-part VFX production toolset:

1. **Browser production workspace** — a local-first shot planner that turns a project bible and shot specification into reproducible, model-agnostic prompts.
2. **Python orchestration package** — the `vfp` CLI and closed-loop pipeline for coordinating LLM planning, ComfyUI renders, QA, corrections, retries and persisted job state.

The browser workspace is a planning and handoff tool; it does **not** generate images or call an LLM. The Python pipeline is the execution layer and requires its own provider/ComfyUI configuration.

## Browser workspace

### Start

```bash
pnpm install --no-frozen-lockfile
pnpm dev
```

### What it does

- Starts with a coherent four-shot sequence instead of an empty template.
- Maintains project-wide visual rules and shot-level camera, movement, lighting, continuity, reference, negative-prompt and seed fields.
- Assembles a complete prompt from explicit fields; it never sends the prompt to a remote service.
- Flags missing production-critical information before handoff.
- Tracks planned, prompt-ready, in-review and approved states, plus planned runtime.
- Imports and exports versioned JSON manifests for backup and handoff.
- Keeps browser edits in local storage. Export a manifest for a portable backup.

The UI works without API keys and makes no external API calls. Do not place secrets in project notes or prompts.

## Python pipeline

Install the CLI and its test dependencies (from source — the package is not published on PyPI):

```bash
python -m pip install -e '.[dev]'
vfp --help
vfp run --help
```

The CLI accepts workflow JSON, natural-language briefs and named templates. It coordinates the configured LLM agents and ComfyUI render service, tracks job state, runs QA, applies bounded corrections/retries and reports machine-readable results when requested.

Configure providers and ComfyUI through a YAML config and/or environment variables. Keep credentials in environment variables or a secret manager; never commit API keys. See `orchestrator/config.py` and the shipped YAML templates for supported configuration fields.

## Validation

```bash
pnpm run check
pnpm test
pnpm run build

python -m pytest -q tests
vfp --help
```

GitHub Actions validates the Python package and browser workspace separately.

## Current limits

- Browser projects are local to the current browser profile until exported; there is no account sync or collaboration backend.
- Prompt quality depends on the references and production constraints supplied by the operator.
- The browser workspace does not claim that a prompt is compatible with every model; it produces a transparent handoff spec.
- A successful local build does not prove an external LLM provider or ComfyUI endpoint is configured or reachable.

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
pytest -q          # 262 tests, no network required
ruff check .
python scripts/benchmark.py
```

## License

MIT — see [LICENSE](LICENSE).

> Note: `pyproject.toml` still declares `license = "Apache-2.0"`; the LICENSE file (MIT) is
> the authoritative one. Fix the metadata before any public release.
