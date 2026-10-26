export type ShotStatus = "planned" | "prompt_ready" | "in_review" | "approved";

export interface VFXShot {
  id: string;
  title: string;
  purpose: string;
  durationSeconds: number;
  status: ShotStatus;
  scene: string;
  camera: string;
  movement: string;
  lighting: string;
  continuity: string;
  referenceNotes: string;
  negativePrompt: string;
  seed: string;
}

export interface VFXProject {
  schemaVersion: 1;
  title: string;
  logline: string;
  visualBible: string;
  modelTarget: string;
  aspectRatio: "16:9" | "9:16" | "1:1" | "2.39:1";
  frameRate: 24 | 25 | 30;
  shots: VFXShot[];
}

const DEFAULT_NEGATIVE = "unwanted text, logos, watermarks, extra fingers, duplicate subjects, inconsistent costume, inconsistent face, flicker, warped geometry, plastic skin, oversharpening";

export function createShot(index: number): VFXShot {
  const n = Math.max(1, Math.floor(index));
  return {
    id: `shot-${n}-${Date.now().toString(36)}`,
    title: `Shot ${String(n).padStart(2, "0")}`,
    purpose: "Advance the story with one clear visual beat.",
    durationSeconds: 5,
    status: "planned",
    scene: "",
    camera: "Medium-wide, eye-level, 35mm equivalent",
    movement: "Slow, controlled dolly-in; no abrupt motion",
    lighting: "Motivated key light, soft fill, stable exposure",
    continuity: "Preserve subject identity, wardrobe, props, geography and screen direction from adjacent shots.",
    referenceNotes: "",
    negativePrompt: DEFAULT_NEGATIVE,
    seed: "",
  };
}

export function createStarterProject(): VFXProject {
  const shots: VFXShot[] = [
    {
      ...createShot(1),
      id: "shot-01",
      title: "01 · Establishing",
      purpose: "Establish place, mood and spatial geography before the character enters.",
      durationSeconds: 6,
      status: "prompt_ready",
      scene: "A rain-darkened futuristic street at blue hour. Practical lights reflect in the pavement; distant traffic is soft and atmospheric.",
      camera: "Wide establishing shot, eye-level, 28mm equivalent; clear foreground, midground and background separation.",
      movement: "Very slow lateral track, constant speed, no handheld shake.",
      lighting: "Cool ambient dusk with restrained warm practicals; preserve highlight detail in wet reflections.",
      continuity: "Set the location palette and direction of travel. Keep signage abstract and unreadable.",
      referenceNotes: "Use as the environment and color reference for the next shots.",
      seed: "2401",
    },
    {
      ...createShot(2),
      id: "shot-02",
      title: "02 · Character reveal",
      purpose: "Introduce the lead while preserving the geography established in Shot 01.",
      durationSeconds: 5,
      status: "planned",
      scene: "The lead enters frame from camera-left and pauses beneath a pool of warm practical light, with the same rain-darkened street behind them.",
      camera: "Medium full shot, 50mm equivalent, three-quarter profile; subject clearly separated from background.",
      movement: "Gentle dolly-in that settles before the final second.",
      lighting: "Same cool ambient dusk and warm practical motivated key as Shot 01; natural skin texture.",
      continuity: "Match the lead's face, hair, costume, silhouette, wetness and direction of travel across all shots.",
      referenceNotes: "Attach the approved character reference before generation; do not invent a new face.",
      seed: "2402",
    },
    {
      ...createShot(3),
      id: "shot-03",
      title: "03 · Detail / insert",
      purpose: "Show one meaningful prop detail that motivates the next story beat.",
      durationSeconds: 4,
      status: "planned",
      scene: "Close insert of the lead's gloved hand holding a small metallic key; rain beads catch the practical light.",
      camera: "Tight insert, 85mm macro-like perspective, shallow but readable depth of field.",
      movement: "Locked camera; only subtle natural hand movement and falling droplets.",
      lighting: "Controlled specular edge on the key, soft fill on the glove, no blown highlights.",
      continuity: "Match glove material, key shape, hand orientation and light direction with the character reveal.",
      referenceNotes: "The prop silhouette must remain consistent if it appears again.",
      seed: "2403",
    },
    {
      ...createShot(4),
      id: "shot-04",
      title: "04 · Resolve",
      purpose: "End on a readable image that leaves room for the following edit.",
      durationSeconds: 6,
      status: "planned",
      scene: "The lead looks toward a distant doorway, then turns slightly toward camera; the street remains the same location.",
      camera: "Medium close-up, 50mm equivalent, eye-line held in the upper third.",
      movement: "Slow push-in ending on a steady final frame suitable for an edit point.",
      lighting: "Maintain the established cool/warm split and realistic contrast; avoid a sudden exposure change.",
      continuity: "Same identity, costume, key, rain state, time of day and screen direction. End with a stable pose.",
      referenceNotes: "Use the approved character and environment references; leave handles for editorial trimming.",
      seed: "2404",
    },
  ];

  return {
    schemaVersion: 1,
    title: "Untitled VFX sequence",
    logline: "A short visual sequence planned shot-by-shot with continuity under explicit control.",
    visualBible: "Cinematic realism; coherent lens language; restrained cool/warm palette; physically motivated light; natural material response; stable character identity; no unmotivated changes between shots.",
    modelTarget: "Model / workflow not selected",
    aspectRatio: "16:9",
    frameRate: 24,
    shots,
  };
}

export function buildShotPrompt(project: VFXProject, shot: VFXShot): string {
  const lines = [
    `PROJECT: ${project.title}`,
    `STORY CONTEXT: ${project.logline}`,
    `VISUAL BIBLE: ${project.visualBible}`,
    `SHOT: ${shot.title} (${shot.durationSeconds}s, ${project.aspectRatio}, ${project.frameRate} fps)`,
    `SHOT PURPOSE: ${shot.purpose}`,
    `SCENE: ${shot.scene.trim() || "[Define the scene before generation]"}`,
    `CAMERA / LENS: ${shot.camera}`,
    `CAMERA MOVEMENT: ${shot.movement}`,
    `LIGHTING: ${shot.lighting}`,
    `CONTINUITY LOCK: ${shot.continuity}`,
    `REFERENCE NOTES: ${shot.referenceNotes.trim() || "Use only references supplied by the production team; do not invent unseen details."}`,
    `NEGATIVE CONSTRAINTS: ${shot.negativePrompt}`,
    `SEED: ${shot.seed.trim() || "Not locked"}`,
    "DELIVERY: One shot only. Preserve the specified framing, action and identity. No titles, captions, logos or transitions. Do not add story beats that are not specified above.",
  ];
  return lines.join("\n");
}

export function validateShot(shot: VFXShot): string[] {
  const issues: string[] = [];
  if (!shot.title.trim()) issues.push("Give the shot a title.");
  if (!shot.scene.trim()) issues.push("Describe the visible action and environment.");
  if (!shot.camera.trim()) issues.push("Specify framing and lens language.");
  if (!shot.continuity.trim()) issues.push("Define what must remain consistent.");
  if (!shot.negativePrompt.trim()) issues.push("Add negative constraints for known failure modes.");
  if (!Number.isFinite(shot.durationSeconds) || shot.durationSeconds < 1 || shot.durationSeconds > 30) {
    issues.push("Duration must be between 1 and 30 seconds.");
  }
  return issues;
}

export function getProjectMetrics(project: VFXProject) {
  const total = project.shots.length;
  const ready = project.shots.filter((shot) => validateShot(shot).length === 0).length;
  const approved = project.shots.filter((shot) => shot.status === "approved").length;
  const duration = project.shots.reduce((sum, shot) => sum + (Number.isFinite(shot.durationSeconds) ? shot.durationSeconds : 0), 0);
  return { total, ready, approved, duration };
}

export function parseProject(raw: string | null): VFXProject {
  if (!raw) return createStarterProject();
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return createStarterProject();
    const candidate = value as Partial<VFXProject>;
    if (candidate.schemaVersion !== 1 || typeof candidate.title !== "string" || !Array.isArray(candidate.shots)) {
      return createStarterProject();
    }
    const fallback = createStarterProject();
    const shots = candidate.shots.filter((shot): shot is VFXShot =>
      Boolean(shot && typeof shot === "object" && typeof (shot as VFXShot).id === "string" && typeof (shot as VFXShot).title === "string"),
    );
    return {
      ...fallback,
      ...candidate,
      title: candidate.title.slice(0, 180),
      logline: typeof candidate.logline === "string" ? candidate.logline.slice(0, 2000) : fallback.logline,
      visualBible: typeof candidate.visualBible === "string" ? candidate.visualBible.slice(0, 4000) : fallback.visualBible,
      modelTarget: typeof candidate.modelTarget === "string" ? candidate.modelTarget.slice(0, 180) : fallback.modelTarget,
      shots: shots.map((shot) => ({
        ...createShot(1),
        ...shot,
        id: shot.id.slice(0, 120),
        title: shot.title.slice(0, 180),
        durationSeconds: Math.min(30, Math.max(1, Number(shot.durationSeconds) || 5)),
        status: ["planned", "prompt_ready", "in_review", "approved"].includes(shot.status) ? shot.status : "planned",
      })),
    };
  } catch {
    return createStarterProject();
  }
}

export function exportProject(project: VFXProject): string {
  return JSON.stringify({ ...project, exportedAt: new Date().toISOString() }, null, 2);
}
