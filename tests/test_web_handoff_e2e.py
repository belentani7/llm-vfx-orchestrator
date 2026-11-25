"""Cross-stack E2E test: Browser Workspace `.vfp-batch.json` -> Python `VFPPipeline` & `JobStore`."""

from __future__ import annotations

import json

import pytest

from orchestrator.pipeline import PipelineState
from orchestrator.store import JobStore
from tests.conftest import FakeComfyUI, StubDirector, StubQA, build_pipeline


@pytest.mark.asyncio
async def test_workspace_exported_vfp_batch_executes_end_to_end(
    pipeline_config, tmp_path
) -> None:
    """Verify the exact JSON structure produced by `exportVfpBatch` in `src/lib/production.ts`
    runs cleanly through `VFPPipeline.run_batch`, records cost metrics, and persists jobs.
    """
    workspace_batch = [
        {
            "job_id": "shot-01",
            "prompt": "PROJECT: Neon Estuary Cut\nSHOT: 01 · Establishing (6s, 2.39:1, 24 fps)",
            "negative_prompt": "unwanted text, logos, watermarks, flicker",
            "max_retries": 2,
            "qa_threshold": 0.85,
            "template": {
                "name": "scene_composition",
                "aspect_ratio": "2.39:1",
                "frame_rate": 24,
                "duration_seconds": 6,
                "seed": 2401,
            },
        },
        {
            "job_id": "shot-02",
            "prompt": "PROJECT: Neon Estuary Cut\nSHOT: 02 · Character reveal (5s, 2.39:1, 24 fps)",
            "negative_prompt": "unwanted text, duplicate subjects",
            "max_retries": 2,
            "qa_threshold": 0.85,
            "template": {
                "name": "scene_composition",
                "aspect_ratio": "2.39:1",
                "frame_rate": 24,
                "duration_seconds": 5,
                "seed": 2402,
            },
        },
    ]

    batch_file = tmp_path / "neon-estuary.vfp-batch.json"
    batch_file.write_text(json.dumps(workspace_batch), encoding="utf-8")

    store = JobStore(tmp_path / "jobs")
    director = StubDirector()
    comfy = FakeComfyUI(render_delay=0.01)
    qa = StubQA(scores=[0.92, 0.89])

    pipeline = build_pipeline(
        pipeline_config,
        comfyui=comfy,
        director=director,
        qa=qa,
        store=store,
    )

    loaded_specs = json.loads(batch_file.read_text(encoding="utf-8"))
    results = await pipeline.run_batch(loaded_specs, concurrency=2)

    assert len(results) == 2
    assert [r.job_id for r in results] == ["shot-01", "shot-02"]
    assert all(r.status is PipelineState.COMPLETED for r in results)
    assert all(r.metrics.get("estimated_cost_usd", 0) > 0 for r in results)
    assert len(director.calls) == 2
    assert store.get("shot-01")["status"] == "completed"
    assert store.get("shot-02")["status"] == "completed"
