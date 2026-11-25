// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { deriveLightingPalette } from "./components/HeroShader";
import { createStarterProject } from "./lib/production";

describe("Workspace E2E happy path, WebGL graceful degradation & WCAG 2.2 AA", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      () => null,
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("completes the full shot-planning, project bible, export/import, and GPU toggle flow", async () => {
    const user = userEvent.setup();
    const createObjectUrlMock = vi.fn(() => "blob:mock-manifest");
    const revokeObjectUrlMock = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: createObjectUrlMock,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: revokeObjectUrlMock,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );

    render(<App />);

    // 1. Starter 4-shot sequence loads with verified metrics
    expect(
      screen.getByRole("heading", { name: /Untitled VFX sequence/i }),
    ).toBeTruthy();
    const metricsRegion = screen.getByLabelText("Production metrics");
    expect(within(metricsRegion).getByText("Total shots")).toBeTruthy();
    expect(within(metricsRegion).getByText(/504 frames/i)).toBeTruthy();

    // 2. Switch to Project Bible tab and customize project continuity
    await user.click(screen.getByRole("tab", { name: /02 \/ Project bible/i }));
    const titleInput = screen.getByLabelText(/Project title/i);
    await user.clear(titleInput);
    await user.type(titleInput, "Neon Estuary Cut");
    await user.selectOptions(screen.getByLabelText(/Aspect ratio/i), "2.39:1");
    expect(
      screen.getByRole("heading", { name: "Neon Estuary Cut" }),
    ).toBeTruthy();

    // 3. Return to Shot Planning, add a 5th shot, complete its scene, and approve it
    await user.click(screen.getByRole("tab", { name: /01 \/ Shot planning/i }));
    await user.click(screen.getByRole("button", { name: /＋ Add shot/i }));
    expect(screen.getByText(/1 item\(s\) to complete/i)).toBeTruthy();

    const sceneInput = screen.getByLabelText(/Scene and visible action/i);
    await user.type(
      sceneInput,
      "Wide crane descent over rain-slicked harbor dock under amber sodium lamps.",
    );
    await user.selectOptions(
      screen.getByLabelText(/Production status/i),
      "approved",
    );
    expect(screen.getByText(/Shot specification complete/i)).toBeTruthy();

    // 4. Verify assembled prompt inherits Project Bible + shot details
    const promptTextarea = screen.getByLabelText(
      /Generated shot prompt/i,
    ) as HTMLTextAreaElement;
    expect(promptTextarea.value).toContain("PROJECT: Neon Estuary Cut");
    expect(promptTextarea.value).toContain("2.39:1");
    expect(promptTextarea.value).toContain("harbor dock under amber sodium");

    // 5. Toggle GPU atmosphere preview pause/resume and verify CSS fallback in JSDOM
    const gpuToggle = screen.getByRole("button", {
      name: /Pause GPU preview/i,
    });
    expect(gpuToggle.getAttribute("aria-pressed")).toBe("false");
    await user.click(gpuToggle);
    expect(gpuToggle.getAttribute("aria-pressed")).toBe("true");
    expect(gpuToggle.textContent).toContain("Resume GPU preview");

    // 6. Export manifest & vfp batch
    await user.click(screen.getByRole("button", { name: /Export manifest/i }));
    expect(screen.getByRole("status").textContent).toContain(
      "Production manifest exported.",
    );
    await user.click(screen.getByRole("button", { name: /Export vfp batch/i }));
    expect(screen.getByRole("status").textContent).toContain(
      "Exported vfp batch (5 shots)",
    );
    expect(createObjectUrlMock).toHaveBeenCalledTimes(2);
    expect(revokeObjectUrlMock).toHaveBeenCalledTimes(2);

    // 7. Import a JSON manifest file and verify full state replacement
    const importedProject = {
      ...createStarterProject(),
      title: "Imported Studio Reel",
      shots: [createStarterProject().shots[0]],
    };
    const file = new File(
      [JSON.stringify(importedProject)],
      "studio-reel.json",
      { type: "application/json" },
    );
    const fileInput = screen.getByLabelText(/Import JSON manifest/i);
    await user.upload(fileInput, file);
    expect(
      await screen.findByRole("heading", { name: "Imported Studio Reel" }),
    ).toBeTruthy();
  });

  it("derives cinema lighting palettes deterministically from shot descriptions", () => {
    expect(deriveLightingPalette("Warm tungsten key").colorC).toBe("#ff5a36");
    expect(deriveLightingPalette("Crimson sodium street spill").colorA).toBe(
      "#ff073a",
    );
    expect(deriveLightingPalette("Cool steel blue fill").colorB).toBe(
      "#5ea3ff",
    );
  });

  it("passes axe-core WCAG 2.2 AA accessibility checks with zero violations on Workspace views", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);

    const axeOptions: axe.RunOptions = {
      runOnly: {
        type: "tag",
        values: [
          "wcag2a",
          "wcag2aa",
          "wcag21a",
          "wcag21aa",
          "wcag22aa",
          "best-practice",
        ],
      },
      rules: {
        // JSDOM does not rasterize CSS backgrounds; exact luminance ratios are verified by scripts/audit-web.mjs
        "color-contrast": { enabled: false },
      },
    };

    const shotsResults = await axe.run(container, axeOptions);
    expect(shotsResults.violations).toEqual([]);

    await user.click(screen.getByRole("tab", { name: /02 \/ Project bible/i }));
    const gpuRateInput = screen.getByLabelText(/GPU rate \(\$\/h\)/i);
    await user.clear(gpuRateInput);
    await user.type(gpuRateInput, "2.40");
    const projectResults = await axe.run(container, axeOptions);
    expect(projectResults.violations).toEqual([]);
  });

  it("passes axe-core WCAG 2.2 AA accessibility checks on all 16 static HTML entrypoints", async () => {
    const pages = [
      "404.html",
      "accesibilidad.html",
      "accessibility.html",
      "ampliacion.html",
      "aviso-legal.html",
      "docs.html",
      "docs/index.html",
      "ecosistema.html",
      "index.html",
      "magic/immersive.html",
      "magic/sfx.html",
      "magic/shader.html",
      "plataforma/PROTOTIPO.html",
      "privacidad.html",
      "producto/landing.html",
      "site/index.html",
    ];

    for (const relPath of pages) {
      const html = readFileSync(resolve(process.cwd(), relPath), "utf8");
      const parser = new DOMParser();
      const parsedDoc = parser.parseFromString(html, "text/html");
      document.documentElement.lang = parsedDoc.documentElement.lang || "en";
      document.title = parsedDoc.title || relPath;
      document.body.innerHTML = parsedDoc.body.innerHTML;

      const results = await axe.run(document.body, {
        runOnly: {
          type: "tag",
          values: [
            "wcag2a",
            "wcag2aa",
            "wcag21a",
            "wcag21aa",
            "wcag22aa",
            "best-practice",
          ],
        },
        rules: {
          "color-contrast": { enabled: false },
        },
      });
      expect(
        results.violations,
        `Accessibility violations in ${relPath}: ${JSON.stringify(results.violations)}`,
      ).toEqual([]);
    }
  });
});
