"""CLI interface for llm-vfx-orchestrator."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click

from .config import PipelineConfig
from .pipeline import VFPPipeline


@click.group()
def main() -> None:
    """llm-vfx-orchestrator — VFX pipeline orchestration via LLMs."""


@main.command()
@click.argument("workflow", type=click.Path(exists=True))
@click.option("--config", "-c", "config_path", type=click.Path(exists=True), default=None, help="Config YAML path")
def run(workflow: str, config_path: str | None) -> None:
    """Execute a VFX workflow."""
    cfg = PipelineConfig.from_yaml(config_path) if config_path else PipelineConfig()
    wf_data = json.loads(Path(workflow).read_text())
    pipeline = VFPPipeline(cfg)
    result = asyncio.run(pipeline.execute(wf_data))

    click.echo(f"Job: {result.job_id}")
    click.echo(f"Status: {result.status.value}")
    click.echo(f"Iterations: {result.iterations}")
    if result.outputs:
        click.echo(f"Outputs: {', '.join(result.outputs)}")
    if result.error:
        click.echo(f"Error: {result.error}")


@main.command()
@click.argument("job_id")
def status(job_id: str) -> None:
    """Check job status."""
    pipeline = VFPPipeline()
    st = pipeline.get_status(job_id)
    if st is None:
        click.echo(f"Job {job_id} not found")
        raise SystemExit(1)
    click.echo(f"Job: {st.job_id}")
    click.echo(f"State: {st.state.value}")
    if st.transitions:
        click.echo("History:")
        for from_s, to_s, reason in st.transitions:
            click.echo(f"  {from_s.value} -> {to_s.value}: {reason}")


@main.command()
@click.argument("job_id")
def retry(job_id: str) -> None:
    """Retry a failed job."""
    pipeline = VFPPipeline()
    st = pipeline.get_status(job_id)
    if st is None:
        click.echo(f"Job {job_id} not found")
        raise SystemExit(1)
    if st.state.value != "failed":
        click.echo(f"Job {job_id} is not in failed state (current: {st.state.value})")
        raise SystemExit(1)
    click.echo(f"Retrying job {job_id}...")
    click.echo("(Retry requires the original workflow — use `vfp run` with the same workflow file)")


if __name__ == "__main__":
    main()
