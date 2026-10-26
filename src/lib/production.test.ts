import { describe, expect, it } from "vitest";
import {
  buildShotPrompt,
  createShot,
  createStarterProject,
  exportProject,
  getProjectMetrics,
  parseProject,
  validateShot,
} from "./production";

describe("VFX production planning core", () => {
  it("starts with a usable four-shot sequence and stable continuity", () => {
    const project = createStarterProject();
    expect(project.shots).toHaveLength(4);
    expect(project.shots.every((shot) => shot.scene.length > 0 && shot.continuity.length > 0)).toBe(true);
    expect(new Set(project.shots.map((shot) => shot.id)).size).toBe(project.shots.length);
    expect(getProjectMetrics(project)).toEqual({ total: 4, ready: 4, approved: 0, duration: 21 });
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
    const shot = { ...createShot(1), scene: "", camera: "", continuity: "", negativePrompt: "", durationSeconds: 60 };
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
    const imported = parseProject(JSON.stringify({
      schemaVersion: 1,
      title: "Imported",
      aspectRatio: "invalid",
      frameRate: 99,
      shots: [{ id: "s1", title: "Untrusted", status: "unknown", durationSeconds: 900, scene: 7 }],
    }));
    expect(imported.title).toBe("Imported");
    expect(imported.aspectRatio).toBe("16:9");
    expect(imported.frameRate).toBe(24);
    expect(imported.shots[0].status).toBe("planned");
    expect(imported.shots[0].durationSeconds).toBe(30);
    expect(imported.shots[0].scene).toBe("");
    expect(imported.shots[0].continuity.length).toBeGreaterThan(0);
  });

  it("exports a versioned JSON manifest that can be imported again", () => {
    const project = createStarterProject();
    const manifest = exportProject(project);
    expect(JSON.parse(manifest).schemaVersion).toBe(1);
    expect(parseProject(manifest).shots).toHaveLength(project.shots.length);
    expect(JSON.parse(manifest).exportedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});
