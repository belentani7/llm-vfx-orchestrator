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

Install the CLI and its test dependencies:

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
