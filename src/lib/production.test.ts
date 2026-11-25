import { describe, expect, it } from "vitest";
import {
  buildShotPrompt,
  createShot,
  createStarterProject,
  estimateProjectBudget,
  estimateShotCost,
  exportProject,
  exportVfpBatch,
  getProjectMetrics,
  parseProject,
  validateShot,
} from "./production";

describe("VFX production planning core", () => {
  it("starts with a usable four-shot sequence and stable continuity", () => {
    const project = createStarterProject();
    expect(project.shots).toHaveLength(4);
    expect(
      project.shots.every(
        (shot) => shot.scene.length > 0 && shot.continuity.length > 0,
      ),
    ).toBe(true);
    expect(new Set(project.shots.map((shot) => shot.id)).size).toBe(
      project.shots.length,
    );
    expect(getProjectMetrics(project)).toEqual({
      total: 4,
      ready: 4,
      approved: 0,
      duration: 21,
    });
  });

  it("assembles a model-agnostic prompt from project and shot constraints", () => {
    const project = createStarterProject();
    const shot = project.shots[1];
    const prompt = buildShotPrompt(project, shot);
    expect(prompt).toContain(project.visualBible);
    expect(prompt).toContain(shot.scene);
    expect(prompt).toContain(shot.camera);
    expect(prompt).toContain(shot.continuity);
    expect(prompt).toContain(shot.negativePrompt);
    expect(prompt).toContain("One shot only");
    expect(prompt).not.toContain("undefined");
  });

  it("reports missing production-critical details instead of silently claiming readiness", () => {
    const shot = {
      ...createShot(1),
      scene: "",
      camera: "",
      continuity: "",
      negativePrompt: "",
      durationSeconds: 60,
    };
    expect(validateShot(shot)).toEqual([
      "Describe the visible action and environment.",
      "Specify framing and lens language.",
      "Define what must remain consistent.",
      "Add negative constraints for known failure modes.",
      "Duration must be between 1 and 30 seconds.",
    ]);
  });

  it("falls back safely for corrupted storage and normalizes imported fields", () => {
    expect(parseProject("{bad json").shots).toHaveLength(4);
    const imported = parseProject(
      JSON.stringify({
        schemaVersion: 1,
        title: "Imported",
        aspectRatio: "invalid",
        frameRate: 99,
        shots: [
          {
            id: "s1",
            title: "Untrusted",
            status: "unknown",
            durationSeconds: 900,
            scene: 7,
          },
        ],
      }),
    );
    expect(imported.title).toBe("Imported");
    expect(imported.aspectRatio).toBe("16:9");
    expect(imported.frameRate).toBe(24);
    expect(imported.shots[0].status).toBe("planned");
    expect(imported.shots[0].durationSeconds).toBe(30);
    expect(imported.shots[0].scene).toBe("");
    expect(imported.shots[0].continuity.length).toBeGreaterThan(0);
  });

  it("deduplicates shot identifiers from imported manifests", () => {
    const project = createStarterProject();
    const duplicated = {
      ...project,
      shots: [
        { ...project.shots[0], id: "same" },
        { ...project.shots[1], id: "same" },
      ],
    };
    const imported = parseProject(JSON.stringify(duplicated));
    expect(new Set(imported.shots.map((shot) => shot.id)).size).toBe(
      imported.shots.length,
    );
  });

  it("exports a versioned JSON manifest that can be imported again", () => {
    const project = createStarterProject();
    const manifest = exportProject(project);
    expect(JSON.parse(manifest).schemaVersion).toBe(1);
    expect(parseProject(manifest).shots).toHaveLength(project.shots.length);
    expect(JSON.parse(manifest).exportedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("estimates per-shot and sequence render cost, frames, and VRAM tier", () => {
    const project = createStarterProject();
    const budget = estimateProjectBudget(project);
    expect(budget.totalFrames).toBe(21 * 24);
    expect(budget.totalRenderSeconds).toBeGreaterThan(0);
    expect(budget.totalEstimatedCostUsd).toBeGreaterThan(0);
    expect(budget.peakVramTierGb).toBe(16);

    const plannedShot = { ...project.shots[0], status: "planned" as const };
    const approvedShot = { ...project.shots[0], status: "approved" as const };
    expect(
      estimateShotCost(project, approvedShot).estimatedCostUsd,
    ).toBeLessThan(estimateShotCost(project, plannedShot).estimatedCostUsd);
  });

  it("exports a vfp CLI batch specification with prompts, seeds, and QA thresholds", () => {
    const project = createStarterProject();
    const rawBatch = exportVfpBatch(project, {
      maxRetries: 2,
      qaThreshold: 0.85,
    });
    const parsed = JSON.parse(rawBatch);
    expect(parsed).toHaveLength(4);
    expect(parsed[0]).toMatchObject({
      job_id: "shot-01",
      max_retries: 2,
      qa_threshold: 0.85,
      template: {
        name: "scene_composition",
        aspect_ratio: "16:9",
        frame_rate: 24,
        duration_seconds: 6,
        seed: 2401,
      },
    });
    expect(parsed[0].prompt).toContain("01 · Establishing");
  });
});
