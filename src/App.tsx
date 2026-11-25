import { useEffect, useMemo, useState } from "react";
import HeroShader, { deriveLightingPalette } from "./components/HeroShader";
import {
  buildShotPrompt,
  createShot,
  createStarterProject,
  DEFAULT_COST_CALIBRATION,
  estimateProjectBudget,
  estimateShotCost,
  exportProject,
  exportVfpBatch,
  getProjectMetrics,
  parseProject,
  validateShot,
  type CostCalibration,
  type ShotStatus,
  type VFXProject,
  type VFXShot,
} from "./lib/production";

const STORAGE_KEY = "llm-vfx-orchestrator.project.v1";
type WorkspaceTab = "shots" | "project";

const statusLabels: Record<ShotStatus, string> = {
  planned: "Planned",
  prompt_ready: "Prompt ready",
  in_review: "In review",
  approved: "Approved",
};

function readProject(): VFXProject {
  try {
    return parseProject(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return createStarterProject();
  }
}

function toFilenameSlug(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "vfx-project"
  );
}

export default function App() {
  const [project, setProject] = useState<VFXProject>(readProject);
  const [selectedShotId, setSelectedShotId] = useState(
    project.shots[0]?.id ?? "",
  );
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("shots");
  const [storageWarning, setStorageWarning] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(project));
      setStorageWarning(false);
    } catch {
      setStorageWarning(true);
    }
  }, [project]);

  const selectedShot =
    project.shots.find((shot) => shot.id === selectedShotId) ??
    project.shots[0] ??
    null;
  const metrics = useMemo(() => getProjectMetrics(project), [project]);
  const budget = useMemo(() => estimateProjectBudget(project), [project]);
  const shotBudget = useMemo(
    () => (selectedShot ? estimateShotCost(project, selectedShot) : null),
    [project, selectedShot],
  );
  const prompt = selectedShot ? buildShotPrompt(project, selectedShot) : "";
  const shotIssues = selectedShot ? validateShot(selectedShot) : [];
  const lightingPalette = useMemo(
    () => deriveLightingPalette(selectedShot?.lighting ?? ""),
    [selectedShot?.lighting],
  );

  const updateProject = <K extends keyof VFXProject>(
    key: K,
    value: VFXProject[K],
  ) => {
    setProject((current) => ({ ...current, [key]: value }));
  };

  const costConfig: CostCalibration = {
    ...DEFAULT_COST_CALIBRATION,
    ...(project.costConfig ?? {}),
  };

  const updateCostConfig = <K extends keyof CostCalibration>(
    key: K,
    value: CostCalibration[K],
  ) => {
    setProject((current) => ({
      ...current,
      costConfig: {
        ...DEFAULT_COST_CALIBRATION,
        ...(current.costConfig ?? {}),
        [key]: value,
      },
    }));
  };

  const updateShot = <K extends keyof VFXShot>(key: K, value: VFXShot[K]) => {
    if (!selectedShot) return;
    setProject((current) => ({
      ...current,
      shots: current.shots.map((shot) =>
        shot.id === selectedShot.id ? { ...shot, [key]: value } : shot,
      ),
    }));
  };

  const addShot = () => {
    const next = createShot(project.shots.length + 1);
    setProject((current) => ({ ...current, shots: [...current.shots, next] }));
    setSelectedShotId(next.id);
    setActiveTab("shots");
    setNotice("Shot added.");
  };

  const removeShot = () => {
    if (
      !selectedShot ||
      !window.confirm(`Delete "${selectedShot.title}"? This cannot be undone.`)
    ) {
      return;
    }
    const remaining = project.shots.filter(
      (shot) => shot.id !== selectedShot.id,
    );
    setProject((current) => ({ ...current, shots: remaining }));
    setSelectedShotId(remaining[0]?.id ?? "");
    setNotice("Shot deleted.");
  };

  const copyPrompt = async () => {
    if (!prompt) return;
    try {
      await navigator.clipboard.writeText(prompt);
      setNotice("Prompt copied to clipboard.");
    } catch {
      setNotice(
        "Clipboard access is unavailable. Select the prompt text and copy it manually.",
      );
    }
  };

  const triggerDownload = (
    payload: string,
    filename: string,
    message: string,
  ) => {
    const blob = new Blob([payload], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setNotice(message);
  };

  const downloadManifest = () => {
    triggerDownload(
      exportProject(project),
      `${toFilenameSlug(project.title)}.json`,
      "Production manifest exported.",
    );
  };

  const downloadVfpBatch = () => {
    triggerDownload(
      exportVfpBatch(project),
      `${toFilenameSlug(project.title)}.vfp-batch.json`,
      `Exported vfp batch (${project.shots.length} shots) for vfp run --batch.`,
    );
  };

  const importManifest = async (file?: File) => {
    if (!file) return;
    try {
      const imported = parseProject(await file.text());
      setProject(imported);
      setSelectedShotId(imported.shots[0]?.id ?? "");
      setNotice("Project imported and normalized.");
    } catch {
      setNotice("Could not read that project file.");
    }
  };

  const resetProject = () => {
    if (
      !window.confirm(
        "Replace the current project with the starter sequence? Export a backup first if you need it.",
      )
    ) {
      return;
    }
    const starter = createStarterProject();
    setProject(starter);
    setSelectedShotId(starter.shots[0]?.id ?? "");
    setNotice("Starter sequence restored.");
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-workspace">
        Skip to workspace
      </a>

      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            VFX
          </div>
          <div>
            <div className="eyebrow-row">
              <p className="eyebrow">PRODUCTION WORKSPACE · LOCAL FIRST</p>
              <nav className="topbar-links" aria-label="Site navigation">
                <a href="index.html">Overview</a>
                <a href="docs.html">Docs</a>
              </nav>
            </div>
            <h1>
              LLM VFX <span>ORCHESTRATOR</span>
            </h1>
          </div>
        </div>
        <div className="top-actions">
          <label className="button button-quiet import-button">
            Import JSON
            <input
              type="file"
              aria-label="Import JSON manifest"
              accept="application/json,.json"
              onChange={(event) => {
                void importManifest(event.target.files?.[0]);
                event.currentTarget.value = "";
              }}
            />
          </label>
          <button
            className="button button-secondary"
            type="button"
            onClick={downloadVfpBatch}
          >
            Export vfp batch
          </button>
          <button
            className="button button-primary"
            type="button"
            onClick={downloadManifest}
          >
            Export manifest ↗
          </button>
        </div>
      </header>

      <main id="main-workspace">
        <section className="project-banner" aria-label="Production summary">
          <div className="project-heading">
            <p className="eyebrow">ACTIVE PRODUCTION</p>
            <h2>{project.title || "Untitled production"}</h2>
            <p className="project-logline">{project.logline}</p>
            <div className="tag-row">
              <span className="tag">{project.aspectRatio}</span>
              <span className="tag">{project.frameRate} fps</span>
              <span className="tag">{project.shots.length} shots</span>
              <span className="tag">{project.modelTarget}</span>
              <span className="tag">Peak VRAM {budget.peakVramTierGb} GB</span>
            </div>
          </div>
          <div className="metrics-grid" aria-label="Production metrics">
            <div className="metric">
              <strong>{metrics.total}</strong>
              <span>Total shots</span>
            </div>
            <div className="metric">
              <strong>{metrics.ready}</strong>
              <span>Prompt complete</span>
            </div>
            <div className="metric">
              <strong>{metrics.approved}</strong>
              <span>Approved</span>
            </div>
            <div className="metric">
              <strong>
                {metrics.duration}s · ${budget.totalEstimatedCostUsd.toFixed(2)}
              </strong>
              <span>
                Runtime &amp; est. GPU/QA ({budget.totalFrames} frames)
              </span>
            </div>
          </div>
        </section>

        {storageWarning && (
          <p className="notice notice-warning" role="alert">
            Browser storage is unavailable or full. Export a JSON manifest to
            preserve your work.
          </p>
        )}
        {notice && (
          <p className="notice" role="status" aria-live="polite">
            <span>{notice}</span>
            <button
              type="button"
              aria-label="Dismiss notice"
              onClick={() => setNotice("")}
            >
              ×
            </button>
          </p>
        )}

        <div
          className="workspace-tabs"
          role="tablist"
          aria-label="Workspace sections"
        >
          <button
            type="button"
            role="tab"
            id="tab-shots"
            aria-selected={activeTab === "shots"}
            aria-controls="panel-shots"
            className={activeTab === "shots" ? "tab active" : "tab"}
            onClick={() => setActiveTab("shots")}
          >
            01 / Shot planning
          </button>
          <button
            type="button"
            role="tab"
            id="tab-project"
            aria-selected={activeTab === "project"}
            aria-controls="panel-project"
            className={activeTab === "project" ? "tab active" : "tab"}
            onClick={() => setActiveTab("project")}
          >
            02 / Project bible
          </button>
        </div>

        {activeTab === "project" ? (
          <section
            id="panel-project"
            role="tabpanel"
            aria-labelledby="tab-project"
            className="panel project-form"
          >
            <div className="section-heading">
              <div>
                <p className="eyebrow">GLOBAL CONTINUITY</p>
                <h2>Project bible</h2>
                <p>Define the rules every shot prompt must inherit.</p>
              </div>
              <button
                type="button"
                className="button button-danger-quiet"
                onClick={resetProject}
              >
                Reset starter
              </button>
            </div>
            <div className="form-grid">
              <label className="field field-wide">
                Project title
                <input
                  value={project.title}
                  maxLength={180}
                  onChange={(event) =>
                    updateProject("title", event.target.value)
                  }
                />
              </label>
              <label className="field field-wide">
                Logline / story context
                <textarea
                  value={project.logline}
                  rows={3}
                  maxLength={2000}
                  onChange={(event) =>
                    updateProject("logline", event.target.value)
                  }
                />
              </label>
              <label className="field field-wide">
                Visual bible
                <textarea
                  value={project.visualBible}
                  rows={4}
                  maxLength={4000}
                  onChange={(event) =>
                    updateProject("visualBible", event.target.value)
                  }
                />
                <span className="field-help">
                  Palette, material language, realism, identity rules and
                  constraints shared by every shot.
                </span>
              </label>
              <label className="field">
                Target model / pipeline
                <input
                  value={project.modelTarget}
                  maxLength={180}
                  onChange={(event) =>
                    updateProject("modelTarget", event.target.value)
                  }
                />
              </label>
              <label className="field">
                Aspect ratio
                <select
                  value={project.aspectRatio}
                  onChange={(event) =>
                    updateProject(
                      "aspectRatio",
                      event.target.value as VFXProject["aspectRatio"],
                    )
                  }
                >
                  <option value="16:9">16:9 · landscape</option>
                  <option value="9:16">9:16 · vertical</option>
                  <option value="1:1">1:1 · square</option>
                  <option value="2.39:1">2.39:1 · cinema</option>
                </select>
              </label>
              <label className="field">
                Frame rate
                <select
                  value={project.frameRate}
                  onChange={(event) =>
                    updateProject(
                      "frameRate",
                      Number(event.target.value) as VFXProject["frameRate"],
                    )
                  }
                >
                  <option value={24}>24 fps</option>
                  <option value={25}>25 fps</option>
                  <option value={30}>30 fps</option>
                </select>
              </label>
              <label className="field">
                GPU rate ($/h)
                <input
                  type="number"
                  min={0}
                  max={100}
                  step="0.05"
                  value={costConfig.gpuHourlyCostUsd}
                  onChange={(event) =>
                    updateCostConfig(
                      "gpuHourlyCostUsd",
                      Math.max(0, Number(event.target.value) || 0),
                    )
                  }
                />
                <span className="field-help">
                  Ref. $1.20/h (calibrate to provider or config.yaml).
                </span>
              </label>
              <label className="field">
                LLM call rate ($/call)
                <input
                  type="number"
                  min={0}
                  max={10}
                  step="0.001"
                  value={costConfig.llmCallCostUsd}
                  onChange={(event) =>
                    updateCostConfig(
                      "llmCallCostUsd",
                      Math.max(0, Number(event.target.value) || 0),
                    )
                  }
                />
                <span className="field-help">
                  Ref. $0.008/call (vision QA + planning).
                </span>
              </label>
              <label className="field">
                Correction retries
                <input
                  type="number"
                  min={0}
                  max={10}
                  step="1"
                  value={costConfig.maxRetries}
                  onChange={(event) =>
                    updateCostConfig(
                      "maxRetries",
                      Math.min(
                        10,
                        Math.max(
                          0,
                          Math.floor(Number(event.target.value) || 0),
                        ),
                      ),
                    )
                  }
                />
                <span className="field-help">
                  Propagated to vfp batch max_retries.
                </span>
              </label>
            </div>
            <div className="callout">
              <strong>Continuity rule</strong>
              <p>
                Project-level rules are inherited by every prompt. Shot-specific
                constraints remain explicit so the prompt can be handed to an
                external model without hidden context.
              </p>
            </div>
          </section>
        ) : (
          <div id="panel-shots" role="tabpanel" aria-labelledby="tab-shots">
            <section className="workbench" aria-label="Shot sequence editor">
              <aside
                className="panel shot-rail"
                aria-label="Edit decision list"
              >
                <div className="section-heading compact">
                  <div>
                    <p className="eyebrow">EDIT DECISION LIST</p>
                    <h2>Sequence</h2>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={addShot}
                    aria-label="Add shot"
                    title="Add shot"
                  >
                    ＋
                  </button>
                </div>
                <div className="shot-list">
                  {project.shots.map((shot, index) => {
                    const issues = validateShot(shot);
                    return (
                      <button
                        key={shot.id}
                        type="button"
                        className={
                          selectedShot?.id === shot.id
                            ? "shot-card selected"
                            : "shot-card"
                        }
                        aria-current={
                          selectedShot?.id === shot.id ? "true" : undefined
                        }
                        onClick={() => setSelectedShotId(shot.id)}
                      >
                        <span className="shot-index">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span className="shot-card-copy">
                          <strong>{shot.title}</strong>
                          <small>
                            {shot.durationSeconds}s ·{" "}
                            {issues.length ? "Needs detail" : "Prompt complete"}
                          </small>
                        </span>
                        <span
                          className={`status-dot status-${shot.status}`}
                          aria-label={statusLabels[shot.status]}
                          title={statusLabels[shot.status]}
                        />
                      </button>
                    );
                  })}
                  {project.shots.length === 0 && (
                    <p className="empty-state">
                      No shots yet. Add a shot to start your sequence.
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  className="button button-secondary add-shot-wide"
                  onClick={addShot}
                >
                  ＋ Add shot
                </button>
                <div className="rail-footer">
                  <span className="status-dot status-approved" /> Approved{" "}
                  <span className="status-dot status-planned" /> Planned
                </div>
              </aside>

              {selectedShot ? (
                <section className="panel shot-editor">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">SHOT SPECIFICATION</p>
                      <h2>{selectedShot.title}</h2>
                      <p>One shot · one intent · explicit continuity.</p>
                    </div>
                    <button
                      type="button"
                      className="button button-danger-quiet"
                      onClick={removeShot}
                    >
                      Delete shot
                    </button>
                  </div>
                  <div className="form-grid">
                    <label className="field field-wide">
                      Shot title
                      <input
                        value={selectedShot.title}
                        maxLength={180}
                        onChange={(event) =>
                          updateShot("title", event.target.value)
                        }
                      />
                    </label>
                    <label className="field">
                      Duration (seconds)
                      <input
                        type="number"
                        min={1}
                        max={30}
                        value={selectedShot.durationSeconds}
                        onChange={(event) =>
                          updateShot(
                            "durationSeconds",
                            Math.min(
                              30,
                              Math.max(1, Number(event.target.value) || 1),
                            ),
                          )
                        }
                      />
                    </label>
                    <label className="field">
                      Production status
                      <select
                        value={selectedShot.status}
                        onChange={(event) =>
                          updateShot("status", event.target.value as ShotStatus)
                        }
                      >
                        {Object.entries(statusLabels).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field field-wide">
                      Story purpose
                      <input
                        value={selectedShot.purpose}
                        maxLength={500}
                        onChange={(event) =>
                          updateShot("purpose", event.target.value)
                        }
                      />
                    </label>
                    <label className="field field-wide">
                      Scene and visible action
                      <textarea
                        value={selectedShot.scene}
                        rows={4}
                        onChange={(event) =>
                          updateShot("scene", event.target.value)
                        }
                        placeholder="Describe only what should be visible in this shot."
                      />
                    </label>
                    <label className="field">
                      Framing / lens
                      <textarea
                        value={selectedShot.camera}
                        rows={3}
                        onChange={(event) =>
                          updateShot("camera", event.target.value)
                        }
                      />
                    </label>
                    <label className="field">
                      Camera movement
                      <textarea
                        value={selectedShot.movement}
                        rows={3}
                        onChange={(event) =>
                          updateShot("movement", event.target.value)
                        }
                      />
                    </label>
                    <label className="field">
                      Lighting
                      <textarea
                        value={selectedShot.lighting}
                        rows={3}
                        onChange={(event) =>
                          updateShot("lighting", event.target.value)
                        }
                      />
                    </label>
                    <label className="field">
                      Continuity lock
                      <textarea
                        value={selectedShot.continuity}
                        rows={3}
                        onChange={(event) =>
                          updateShot("continuity", event.target.value)
                        }
                      />
                    </label>
                    <label className="field field-wide">
                      Reference notes
                      <textarea
                        value={selectedShot.referenceNotes}
                        rows={2}
                        onChange={(event) =>
                          updateShot("referenceNotes", event.target.value)
                        }
                        placeholder="Which approved image, costume, prop or previous shot should be referenced?"
                      />
                    </label>
                    <label className="field field-wide">
                      Negative constraints
                      <textarea
                        value={selectedShot.negativePrompt}
                        rows={2}
                        onChange={(event) =>
                          updateShot("negativePrompt", event.target.value)
                        }
                      />
                    </label>
                    <label className="field">
                      Seed / generation ID
                      <input
                        value={selectedShot.seed}
                        onChange={(event) =>
                          updateShot("seed", event.target.value)
                        }
                        placeholder="Optional; record it when locked"
                      />
                    </label>
                  </div>
                  <div
                    className={
                      shotIssues.length
                        ? "validation-box validation-needs-work"
                        : "validation-box validation-ready"
                    }
                  >
                    <strong>
                      {shotIssues.length
                        ? `${shotIssues.length} item(s) to complete`
                        : "Shot specification complete"}
                    </strong>
                    {shotIssues.length > 0 && (
                      <ul>
                        {shotIssues.map((issue) => (
                          <li key={issue}>{issue}</li>
                        ))}
                      </ul>
                    )}
                    {shotIssues.length === 0 && (
                      <p>
                        This shot has the minimum information needed for a
                        reproducible prompt handoff.
                      </p>
                    )}
                  </div>
                </section>
              ) : (
                <section className="panel empty-editor">
                  <div className="empty-symbol">＋</div>
                  <h2>Build your first shot</h2>
                  <p>
                    Add a shot to define framing, motion, lighting and
                    continuity.
                  </p>
                  <button
                    type="button"
                    className="button button-primary"
                    onClick={addShot}
                  >
                    Add shot
                  </button>
                </section>
              )}
            </section>

            {selectedShot && (
              <section
                className="panel prompt-panel"
                aria-label="Prompt and optical preview"
              >
                <div className="handoff-grid">
                  <HeroShader
                    compact
                    title={`Optical Atmosphere · ${selectedShot.title}`}
                    subtitle={selectedShot.camera}
                    colorA={lightingPalette.colorA}
                    colorB={lightingPalette.colorB}
                    colorC={lightingPalette.colorC}
                  />
                  {shotBudget && (
                    <div
                      className="budget-strip"
                      aria-label="Shot render budget"
                    >
                      <div>
                        <span>Frames</span>
                        <strong>{shotBudget.frames}f</strong>
                      </div>
                      <div>
                        <span>Est. GPU</span>
                        <strong>~{shotBudget.estimatedRenderSeconds}s</strong>
                      </div>
                      <div>
                        <span>VRAM Tier</span>
                        <strong>{shotBudget.vramTierGb} GB</strong>
                      </div>
                      <div>
                        <span>Est. Shot Cost</span>
                        <strong>
                          ${shotBudget.estimatedCostUsd.toFixed(3)}
                        </strong>
                      </div>
                    </div>
                  )}
                </div>

                <div className="section-heading">
                  <div>
                    <p className="eyebrow">MODEL-AGNOSTIC HANDOFF</p>
                    <h2>Prompt assembly</h2>
                    <p>
                      Generated from the project bible and selected shot fields.
                      Nothing is sent to an external service.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="button button-primary"
                    onClick={() => {
                      void copyPrompt();
                    }}
                  >
                    Copy prompt
                  </button>
                </div>
                <textarea
                  className="prompt-output"
                  aria-label="Generated shot prompt"
                  readOnly
                  value={prompt}
                  rows={14}
                />
                <div className="prompt-footer">
                  <span>
                    CLI handoff:{" "}
                    <code>
                      vfp run --batch {toFilenameSlug(project.title)}
                      .vfp-batch.json
                    </code>
                  </span>
                  <span>{prompt.length.toLocaleString()} characters</span>
                </div>
              </section>
            )}
          </div>
        )}
      </main>

      <footer className="app-footer">
        <span>LLM VFX Orchestrator · local-first production planning</span>
        <span>
          No API keys · no network calls · export your manifest for backup
        </span>
      </footer>
    </div>
  );
}
