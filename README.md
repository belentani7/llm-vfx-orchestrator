# llm-vfx-orchestrator

Autonomous VFX pipeline orchestration using LLMs (Claude, Qwen, GLM) connected to ComfyUI APIs. Automates render error correction through an intelligent feedback loop.

## Architecture

```
DirectorAgent (Claude)     ÔåÆ  Workflow planning, JSON generation
QAInspectorAgent (Qwen)    ÔåÆ  Visual quality assessment
AssetManagerAgent (GLM)    ÔåÆ  RAG for LoRAs, models, textures
CorrectionAgent            ÔåÆ  Generates fix patches
        Ôåô
  ComfyUI API (queue / websocket / result)
        Ôåô
  Feedback Loop (analyze ÔåÆ correct ÔåÆ re-render ÔåÆ QA)
```

## Installation

```bash
pip install llm-vfx-orchestrator
```

Or from source:

```bash
git clone https://github.com/belentani7/llm-vfx-orchestrator.git
cd llm-vfx-orchestrator
pip install -e ".[dev]"
```

### Requirements

- Python 3.11+
- A running ComfyUI instance (default: `http://127.0.0.1:8188`)
- API keys for at least one LLM provider (set via environment or config YAML)

## Quick Start

```bash
# Run a pipeline with default config
vfp run workflow.json

# Run with custom config
vfp run workflow.json --config config.yaml

# Check job status
vfp status <job_id>

# Retry a failed job
vfp retry <job_id>
```

## Configuration

Create a `config.yaml`:

```yaml
comfyui:
  host: "127.0.0.1"
  port: 8188
  timeout: 300

llm:
  claude:
    model: "claude-sonnet-4-20250514"
    api_key: "${ANTHROPIC_API_KEY}"
  qwen:
    model: "qwen-vl-max"
    api_key: "${DASHSCOPE_API_KEY}"
  glm:
    model: "glm-4v-plus"
    api_key: "${ZHIPUAI_API_KEY}"

pipeline:
  max_retries: 3
  qa_threshold: 0.8
```

## Pipeline Templates

Pre-built templates in `orchestrator/templates/`:

| Template | Description |
|---|---|
| `character_generation.yaml` | Character art with style LoRAs |
| `environment_generation.yaml` | Environment / scene generation |
| `product_render.yaml` | Product photography renders |

## How the Feedback Loop Works

1. **Director** generates a ComfyUI workflow JSON from the user prompt
2. **ComfyUI** executes the render via queue + websocket
3. **QA Inspector** evaluates the output against quality criteria
4. If quality is below threshold, the **Correction Agent** patches the workflow
5. Steps 2-4 repeat up to `max_retries` times
6. If still failing, the pipeline escalates for manual review

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

Apache 2.0 ÔÇö see [LICENSE](LICENSE).
