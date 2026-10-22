"""CLI interface for llm-vfx-orchestrator (``vfp``)."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import click

from . import __version__
from .comfyui_client import ComfyUIClient
from .config import PipelineConfig
from .pipeline import VFPPipeline
from .template import available_templates, load_template
from .utils import truncate, utcnow

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format=LOG_FORMAT,
        datefmt="%H:%M:%S",
    )


def _load_config(config_path: str | None, overrides: tuple[str, ...], store_dir: str | None) -> PipelineConfig:
    try:
        base = PipelineConfig.from_yaml(config_path) if config_path else PipelineConfig()
        config = PipelineConfig.from_env(base)
        if store_dir:
            config.store_dir = store_dir
        if overrides:
            config.with_overrides(list(overrides))
        return config
    except Exception as exc:  # noqa: BLE001 - invalid overrides must also be clean errors
        raise click.ClickException(f"invalid configuration: {exc}") from exc


def _make_pipeline(config: PipelineConfig) -> VFPPipeline:
    return VFPPipeline(config)


common_options = [
    click.option("--config", "-c", "config_path", type=click.Path(exists=True, dir_okay=False), default=None,
                 help="Config YAML path"),
    click.option("--set", "overrides", multiple=True, metavar="KEY=VALUE",
                 help="Override any config key (e.g. --set pipeline.qa_threshold=0.9)"),
    click.option("--store", "store_dir", default=None, help="Job store directory"),
    click.option("--verbose", "-v", is_flag=True, help="Verbose logs"),
]


def _with_common(func: Any) -> Any:
    for option in reversed(common_options):
        func = option(func)
    return func


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="vfp")
def main() -> None:
    """llm-vfx-orchestrator — autonomous VFX pipeline orchestration via LLMs + ComfyUI."""


@main.command()
@click.argument("workflow", required=False, type=click.Path(exists=True, dir_okay=False))
@click.option("--prompt", "-p", default=None, help="Natural-language brief (Director plans the graph)")
@click.option("--template", "-t", default=None, help=f"Template name or path ({', '.join(available_templates())})")
@click.option("--batch", "batch_files", multiple=True, type=click.Path(exists=True, dir_okay=False),
              help="JSON file with a workflow or a list of jobs (repeatable)")
@click.option("--concurrency", "-j", type=int, default=None, help="How many jobs to run at once")
@click.option("--max-retries", type=int, default=None, help="Override pipeline.max_retries")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
@_with_common
def run(
    workflow: str | None,
    prompt: str | None,
    template: str | None,
    batch_files: tuple[str, ...],
    concurrency: int | None,
    max_retries: int | None,
    as_json: bool,
    config_path: str | None,
    overrides: tuple[str, ...],
    store_dir: str | None,
    verbose: bool,
) -> None:
    """Execute a VFX workflow (from a file, a prompt, or a batch file)."""
    _configure_logging(verbose)
    config = _load_config(config_path, overrides, store_dir)
    jobs: list[Any] = []

    for batch_file in batch_files:
        payload = json.loads(Path(batch_file).read_text(encoding="utf-8"))
        jobs.extend(payload if isinstance(payload, list) else [payload])
    if workflow:
        jobs.append(json.loads(Path(workflow).read_text(encoding="utf-8")))
    if prompt:
        jobs.append({"prompt": prompt, "template": template})

    if not jobs:
        raise click.UsageError("provide a WORKFLOW file, --prompt, or --batch")
    if template and not prompt:
        # Only prompt-driven jobs understand a template; raw graphs must stay untouched.
        jobs = [
            {**job, "template": template}
            if isinstance(job, dict) and "prompt" in job and "workflow" not in job
            else job
            for job in jobs
        ]

    try:
        results = asyncio.run(
            _run_jobs(config, jobs, concurrency=concurrency, max_retries=max_retries)
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean message, never a traceback
        raise click.ClickException(f"{type(exc).__name__}: {exc}") from exc

    if as_json:
        click.echo(json.dumps([result.as_dict() for result in results], indent=2, ensure_ascii=False))
    else:
        for result in results:
            _print_result(result)
    if any(not result.ok for result in results):
        raise SystemExit(1)


@main.command()
@click.option("--prompt", "-p", required=True, help="Natural-language brief")
@click.option("--template", "-t", default=None, help="Template name or path")
@click.option("--use-assets/--no-assets", "use_assets", default=None, help="Consult the asset manager")
@click.option("--out", "-o", "out_path", type=click.Path(dir_okay=False), default=None,
              help="Write the workflow JSON here (default: stdout)")
@_with_common
def plan(
    prompt: str,
    template: str | None,
    use_assets: bool | None,
    out_path: str | None,
    config_path: str | None,
    overrides: tuple[str, ...],
    store_dir: str | None,
    verbose: bool,
) -> None:
    """Plan a workflow from a prompt without rendering it."""
    _configure_logging(verbose)
    config = _load_config(config_path, overrides, store_dir)

    async def _go() -> dict[str, Any]:
        pipeline = _make_pipeline(config)
        try:
            return await pipeline.plan_prompt(prompt, template=template, use_assets=use_assets)
        finally:
            await pipeline.close()

    try:
        workflow = asyncio.run(_go())
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"{type(exc).__name__}: {exc}") from exc
    serialized = json.dumps(workflow, indent=2, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(serialized, encoding="utf-8")
        click.echo(f"Workflow written to {out_path} ({len(workflow)} nodes)")
    else:
        click.echo(serialized)


@main.command()
@click.argument("job_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
@_with_common
def status(
    job_id: str,
    as_json: bool,
    config_path: str | None,
    overrides: tuple[str, ...],
    store_dir: str | None,
    verbose: bool,
) -> None:
    """Check the status of a job (in-memory or persisted)."""
    _configure_logging(verbose)
    config = _load_config(config_path, overrides, store_dir)
    pipeline = _make_pipeline(config)
    record = pipeline.get_job(job_id)
    state = pipeline.get_status(job_id)
    if state is None:
        click.echo(f"Job {job_id} not found")
        raise SystemExit(1)
    if as_json:
        payload = {"job_id": state.job_id, "state": state.state.value}
        if record:
            payload.update(
                {
                    key: record.get(key)
                    for key in ("score", "best_score", "iterations", "error", "escalation_reason",
                                "started_at", "finished_at", "outputs", "corrections")
                }
            )
        payload["transitions"] = [
            {"from": frm.value, "to": to.value, "reason": reason} for frm, to, reason in state.transitions
        ]
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    click.echo(f"Job: {state.job_id}")
    click.echo(f"State: {state.state.value}")
    if record:
        if record.get("score") is not None:
            click.echo(f"Score: {record['score']}")
        if record.get("iterations") is not None:
            click.echo(f"Renders: {record['iterations']}")
        if record.get("outputs"):
            click.echo(f"Outputs: {', '.join(record['outputs'])}")
        if record.get("error"):
            click.echo(f"Error: {record['error']}")
        if record.get("escalation_reason"):
            click.echo(f"Escalated: {record['escalation_reason']}")
    if state.transitions:
        click.echo("History:")
        for from_state, to_state, reason in state.transitions:
            click.echo(f"  {from_state.value} -> {to_state.value}: {reason}")


@main.command()
@click.option("--limit", "-n", type=int, default=20, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
@_with_common
def jobs(
    limit: int,
    as_json: bool,
    config_path: str | None,
    overrides: tuple[str, ...],
    store_dir: str | None,
    verbose: bool,
) -> None:
    """List recent jobs from the store."""
    _configure_logging(verbose)
    config = _load_config(config_path, overrides, store_dir)
    records = _make_pipeline(config).list_jobs(limit=limit)
    if as_json:
        click.echo(json.dumps(records, indent=2, ensure_ascii=False, default=str))
        return
    if not records:
        click.echo(f"No jobs in {config.jobs_dir}")
        return
    click.echo(f"{'JOB':10} {'STATUS':10} {'SCORE':>6} {'RENDERS':>7}  STARTED")
    for record in records:
        score = record.get("score")
        score_text = f"{float(score):.3f}" if isinstance(score, (int, float)) else "  -  "
        click.echo(
            f"{str(record.get('job_id')):10} {str(record.get('status', '?')):10} "
            f"{score_text:>6} {record.get('iterations', 0):>7}  {record.get('started_at', '')}"
        )


@main.command()
@click.argument("job_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
@_with_common
def retry(
    job_id: str,
    as_json: bool,
    config_path: str | None,
    overrides: tuple[str, ...],
    store_dir: str | None,
    verbose: bool,
) -> None:
    """Re-run a stored job with its original workflow/prompt."""
    _configure_logging(verbose)
    config = _load_config(config_path, overrides, store_dir)
    try:
        results = asyncio.run(_retry_job(config, job_id))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"{type(exc).__name__}: {exc}") from exc
    if as_json:
        click.echo(json.dumps([result.as_dict() for result in results], indent=2, ensure_ascii=False))
    else:
        click.echo(f"Retrying job {job_id}…")
        for result in results:
            _print_result(result)
    if any(not result.ok for result in results):
        raise SystemExit(1)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
@_with_common
def doctor(
    as_json: bool,
    config_path: str | None,
    overrides: tuple[str, ...],
    store_dir: str | None,
    verbose: bool,
) -> None:
    """Check config, LLM providers, job store and ComfyUI connectivity."""
    _configure_logging(verbose)
    config = _load_config(config_path, overrides, store_dir)

    async def _check_comfy() -> tuple[bool, str]:
        client = ComfyUIClient(config.comfyui)
        try:
            ok = await client.ping()
            detail = "reachable"
            if ok:
                try:
                    stats = await client.system_stats()
                    devices = stats.get("devices") or []
                    if devices:
                        name = devices[0].get("name", "device")
                        vram_total = devices[0].get("vram_total")
                        detail = f"reachable · {name}"
                        if vram_total:
                            detail += f" · {int(vram_total) / 1e9:.1f} GB VRAM"
                except Exception as exc:  # noqa: BLE001
                    detail = f"reachable (stats unavailable: {truncate(str(exc), 80)})"
            else:
                detail = "unreachable"
            return ok, detail
        finally:
            await client.close()

    comfy_ok, comfy_detail = asyncio.run(_check_comfy())
    providers = config.llm.configured()
    report = {
        "version": __version__,
        "checked_at": utcnow().isoformat(),
        "comfyui": {
            "url": config.comfyui.base_url,
            "ok": comfy_ok,
            "detail": comfy_detail,
            "max_concurrent_renders": config.comfyui.max_concurrent_renders,
            "ws_timeout": config.comfyui.ws_timeout,
        },
        "llm": {
            "providers": providers,
            "fallbacks": config.llm.fallbacks,
            "ok": bool(providers),
        },
        "pipeline": {
            "qa_threshold": config.qa_threshold,
            "max_retries": config.max_retries,
            "concurrency": config.concurrency,
            "qa_concurrency": config.qa_concurrency,
        },
        "store": {"dir": str(config.jobs_dir), "ok": config.jobs_dir.parent.exists()},
        "templates": available_templates(),
    }
    if as_json:
        click.echo(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        click.echo(f"vfp {report['version']}")
        click.echo(f"ComfyUI   {'OK ' if comfy_ok else 'FAIL'} {report['comfyui']['url']} — {comfy_detail}")
        click.echo(f"LLM       {'OK ' if providers else 'FAIL'} providers: {', '.join(providers) or 'none configured'}")
        if config.llm.fallbacks:
            click.echo(f"          fallbacks: {', '.join(config.llm.fallbacks)}")
        click.echo(f"Pipeline  qa_threshold={config.qa_threshold} max_retries={config.max_retries} "
                   f"concurrency={config.concurrency}")
        click.echo(f"Store     {report['store']['dir']}")
        click.echo(f"Templates {', '.join(report['templates']) or 'none'}")
    if not comfy_ok or not providers:
        raise SystemExit(1)


@main.command("templates")
def templates_command() -> None:
    """List bundled templates."""
    for name in available_templates():
        try:
            data = load_template(name)
        except Exception:  # noqa: BLE001
            continue
        click.echo(f"{name:26} {data.get('negative_prompt', '')[:60]}")


async def _run_jobs(
    config: PipelineConfig,
    jobs: list[Any],
    *,
    concurrency: int | None,
    max_retries: int | None,
) -> list[Any]:
    if max_retries is not None:
        config.max_retries = max_retries
    pipeline = _make_pipeline(config)
    try:
        return list(await pipeline.run_batch(jobs, concurrency=concurrency))
    finally:
        await pipeline.close()


async def _retry_job(config: PipelineConfig, job_id: str) -> list[Any]:
    pipeline = _make_pipeline(config)
    try:
        return [await pipeline.run_retry(job_id)]
    except KeyError as exc:
        click.echo(str(exc).strip("'\""))
        raise SystemExit(1) from exc
    finally:
        await pipeline.close()


def _print_result(result: Any) -> None:
    click.echo(f"Job: {result.job_id}")
    click.echo(f"Status: {result.status.value}")
    click.echo(f"Renders: {result.iterations}")
    if result.score is not None:
        click.echo(f"Score: {result.score:.3f}")
    if result.outputs:
        click.echo(f"Outputs: {', '.join(result.outputs)}")
    if result.corrections:
        click.echo(f"Corrections: {len(result.corrections)}")
    if result.escalation_reason:
        click.echo(f"Escalated: {result.escalation_reason}")
    if result.error:
        click.echo(f"Error: {result.error}")


if __name__ == "__main__":
    main()
