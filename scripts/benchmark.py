#!/usr/bin/env python3
"""Throughput benchmark for the orchestration layer (no GPU / no network required).

Simulates ComfyUI render latency and measures how many jobs per second the pipeline
finishes at different concurrency levels, plus QA fan-out concurrency.

    python scripts/benchmark.py --jobs 24 --render-ms 50 --concurrency 1,2,4,8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from orchestrator.comfyui_client import OutputImage, RenderOutcome
from orchestrator.config import LLMConfig, LLMProviderConfig, PipelineConfig
from orchestrator.pipeline import VFPPipeline
from orchestrator.store import JobStore

WORKFLOW = {
    "3": {"class_type": "KSampler", "inputs": {"steps": 20, "model": ["4", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["4", 0]}},
}


@dataclass
class SimulatedComfyUI:
    """ComfyUI stand-in with configurable render latency and QA-visible output."""

    latency_s: float = 0.05
    images: int = 1

    def __post_init__(self) -> None:
        from orchestrator.config import ComfyUIConfig

        self.config = ComfyUIConfig()
        self.client_id = "bench"
        self.inflight = 0
        self.peak_inflight = 0
        self.renders = 0

    async def queue_prompt(self, workflow: dict, extra_data: dict | None = None) -> str:
        self.renders += 1
        return f"bench-{self.renders}"

    async def wait_for_prompt(self, prompt_id: str, timeout: float | None = None) -> RenderOutcome:
        self.inflight += 1
        self.peak_inflight = max(self.peak_inflight, self.inflight)
        try:
            await asyncio.sleep(self.latency_s)
            return RenderOutcome(status="success", prompt_id=prompt_id)
        finally:
            self.inflight -= 1

    async def get_output_images(self, prompt_id: str) -> list[OutputImage]:
        return [OutputImage(f"{prompt_id}_{i}.png") for i in range(self.images)]

    async def download_image(self, image, **kwargs) -> bytes:
        return b"\x89PNG" + b"0" * 512

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None


class SimulatedQA:
    role = "qwen"

    def __init__(self, latency_s: float = 0.02, score: float = 0.93) -> None:
        self.latency_s = latency_s
        self.score = score
        self.inflight = 0
        self.peak_inflight = 0

    async def inspect(self, image_description="", criteria="", *, image=None, image_media_type="image/png",
                      extra_context="", client=None):
        self.inflight += 1
        self.peak_inflight = max(self.peak_inflight, self.inflight)
        try:
            await asyncio.sleep(self.latency_s)
            return {"score": self.score, "issues": [], "summary": "bench"}
        finally:
            self.inflight -= 1


async def run_once(jobs: int, concurrency: int, render_ms: float, qa_ms: float, images: int) -> dict:
    config = PipelineConfig(
        concurrency=concurrency,
        qa_concurrency=max(1, concurrency),
        llm=LLMConfig(
            claude=LLMProviderConfig(model="c", api_key="k"),
            qwen=LLMProviderConfig(model="q", api_key="k"),
            glm=LLMProviderConfig(model="g", api_key="k"),
        ),
    )
    comfy = SimulatedComfyUI(latency_s=render_ms / 1000, images=images)
    qa = SimulatedQA(latency_s=qa_ms / 1000)
    with tempfile.TemporaryDirectory() as tmp:
        pipeline = VFPPipeline(
            config, comfyui=comfy, qa=qa, store=JobStore(Path(tmp) / "jobs")  # type: ignore[arg-type]
        )
        started = time.perf_counter()
        results = await pipeline.run_batch([WORKFLOW] * jobs, concurrency=concurrency)
        elapsed = time.perf_counter() - started
    completed = sum(1 for result in results if result.ok)
    return {
        "concurrency": concurrency,
        "jobs": jobs,
        "completed": completed,
        "seconds": round(elapsed, 3),
        "jobs_per_s": round(jobs / elapsed, 2),
        "peak_renders": comfy.peak_inflight,
        "peak_qa": qa.peak_inflight,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=24)
    parser.add_argument("--render-ms", type=float, default=50.0)
    parser.add_argument("--qa-ms", type=float, default=20.0)
    parser.add_argument("--images", type=int, default=2, help="rendered images per job")
    parser.add_argument("--concurrency", default="1,2,4,8")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    levels = [int(value) for value in args.concurrency.split(",") if value.strip()]
    print(
        f"jobs={args.jobs} render={args.render_ms}ms qa={args.qa_ms}ms "
        f"images/job={args.images} repeat={args.repeat}"
    )
    print(f"{'conc':>5} {'ok':>4} {'secs':>8} {'jobs/s':>8} {'speedup':>8} {'peak render':>12} {'peak qa':>8}")
    baseline: float | None = None
    summary = []
    for level in levels:
        runs = [
            asyncio.run(run_once(args.jobs, level, args.render_ms, args.qa_ms, args.images))
            for _ in range(args.repeat)
        ]
        seconds = statistics.median(run["seconds"] for run in runs)
        jobs_per_s = args.jobs / seconds
        baseline = baseline if baseline is not None else jobs_per_s
        summary.append({"concurrency": level, "seconds": round(seconds, 3), "jobs_per_s": round(jobs_per_s, 2)})
        print(
            f"{level:>5} {runs[0]['completed']:>4} {seconds:>8.3f} {jobs_per_s:>8.2f} "
            f"{jobs_per_s / baseline:>7.2f}x {runs[0]['peak_renders']:>12} {runs[0]['peak_qa']:>8}"
        )
    print()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
