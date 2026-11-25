#!/usr/bin/env node
/**
 * audit-web.mjs — Auditoría forense de HTML semántico (vía DOM real JSDOM),
 * enlaces internos, privacidad/cero peticiones externas, contraste WCAG 2.2 AA,
 * ciclo de vida WebGL y presupuesto de rendimiento sobre `dist/`.
 *
 * Uso:
 *   node scripts/audit-web.mjs            # Informe legible en consola
 *   node scripts/audit-web.mjs --json     # Salida estructurada JSON
 *   node scripts/audit-web.mjs --help     # Ayuda y opciones
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { JSDOM } from "jsdom";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = new Set(process.argv.slice(2));

if (args.has("--help") || args.has("-h")) {
  console.log(`Uso: node scripts/audit-web.mjs [opciones]

Audita integridad HTML, enlaces locales, ausencia de peticiones remotas bloqueantes,
contraste WCAG 2.2 AA de la paleta, ciclo de vida WebGL/GPU y presupuesto de bundle en dist/.

Opciones:
  --json      Imprime el informe completo en formato JSON
  --no-dist   Omite la auditoría del directorio de compilación dist/
  -h, --help  Muestra esta ayuda y termina
`);
  process.exit(0);
}

const SKIP_DIRS = new Set([
  ".git",
  ".git.corrupt",
  "node_modules",
  ".venv",
  "dist",
  "coverage",
]);

function walkFilesByExt(dir, extension, skipSet = SKIP_DIRS) {
  const results = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (skipSet.has(entry.name)) continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...walkFilesByExt(full, extension, skipSet));
    } else if (entry.isFile() && entry.name.endsWith(extension)) {
      results.push(full);
    }
  }
  return results.sort();
}

function srgbChannel(hexByte) {
  const c = hexByte / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex) {
  const clean = hex.replace("#", "").trim();
  const full =
    clean.length === 3
      ? `${clean[0]}${clean[0]}${clean[1]}${clean[1]}${clean[2]}${clean[2]}`
      : clean;
  const n = Number.parseInt(full, 16);
  const r = srgbChannel((n >> 16) & 255);
  const g = srgbChannel((n >> 8) & 255);
  const b = srgbChannel(n & 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(fg, bg) {
  const l1 = luminance(fg);
  const l2 = luminance(bg);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return Number(((lighter + 0.05) / (darker + 0.05)).toFixed(2));
}

const URI_SCHEME_RE = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;

const checks = [];
const errors = [];

function recordCheck(name, ok, detail = "") {
  checks.push({ name, ok, detail });
  if (!ok) errors.push(`${name}${detail ? `: ${detail}` : ""}`);
}

// 1. Auditoría semántica y de enlaces sobre páginas HTML fuente usando JSDOM
const sourceHtmlFiles = walkFilesByExt(ROOT, ".html");
for (const filePath of sourceHtmlFiles) {
  const rel = filePath.slice(ROOT.length + 1);
  const html = readFileSync(filePath, "utf8");
  const dom = new JSDOM(html);
  const doc = dom.window.document;

  const hasDoctype = Boolean(doc.doctype && doc.doctype.name === "html");
  const hasLang = Boolean(doc.documentElement.getAttribute("lang")?.trim());
  recordCheck(`${rel}: doctype y lang`, hasDoctype && hasLang);

  const visibleClone = doc.body.cloneNode(true);
  for (const node of visibleClone.querySelectorAll("script, style")) {
    node.remove();
  }
  const visibleText = visibleClone.textContent || "";
  recordCheck(
    `${rel}: sin JS plano fuera de <script>`,
    !visibleText.includes("/* Hero Shader WebGL */"),
  );

  const mainCount = doc.querySelectorAll("main").length;
  const headerCount = doc.querySelectorAll("header").length;
  const footerCount = doc.querySelectorAll("footer").length;
  const isReactShell = rel === "workspace.html";
  const validLandmarks = isReactShell
    ? Boolean(doc.getElementById("root"))
    : mainCount === 1 && headerCount === 1 && footerCount === 1;
  recordCheck(
    `${rel}: landmarks únicos (header/main/footer)`,
    validLandmarks,
    `header=${headerCount}, main=${mainCount}, footer=${footerCount}`,
  );

  recordCheck(
    `${rel}: sin mojibake ni placeholders residuales`,
    !/Ã[\x80-\xBF]|â€/.test(html) &&
      !html.includes("$structure_note") &&
      !doc.querySelector("[data-webgl-lab]"),
  );

  const anchors = [...doc.querySelectorAll("a")];
  const missingHref = anchors.filter(
    (a) => !a.getAttribute("href") || !a.getAttribute("href").trim(),
  );
  recordCheck(
    `${rel}: todos los <a> tienen href válido`,
    missingHref.length === 0,
    missingHref.length ? `${missingHref.length} sin href` : "",
  );

  const resourceTargets = [];
  for (const el of doc.querySelectorAll("[href], [src]")) {
    const val = el.getAttribute("href") || el.getAttribute("src") || "";
    if (val.trim()) resourceTargets.push(val.trim());
  }

  const brokenLocal = [];
  const externalBlocking = [];
  for (const rawTarget of resourceTargets) {
    if (rawTarget.startsWith("#")) continue;
    if (URI_SCHEME_RE.test(rawTarget)) {
      if (
        /^https?:\/\/(fonts\.googleapis\.com|fonts\.gstatic\.com|cdn\.|unpkg\.com)/i.test(
          rawTarget,
        )
      ) {
        externalBlocking.push(rawTarget);
      }
      continue;
    }
    const cleanRel = rawTarget.split("#")[0].split("?")[0];
    if (!cleanRel) continue;
    const candidate = cleanRel.startsWith("/")
      ? join(ROOT, cleanRel.slice(1))
      : resolve(dirname(filePath), cleanRel);
    if (!existsSync(candidate)) {
      brokenLocal.push(rawTarget);
    }
  }

  recordCheck(
    `${rel}: enlaces y activos locales existen`,
    brokenLocal.length === 0,
    brokenLocal.join(", "),
  );
  recordCheck(
    `${rel}: cero recursos externos bloqueantes`,
    externalBlocking.length === 0,
    externalBlocking.join(", "),
  );
}

// 2. Auditoría CSS: cero @import remotos y cero z-index desmesurados
for (const cssPath of walkFilesByExt(ROOT, ".css")) {
  const rel = cssPath.slice(ROOT.length + 1);
  const css = readFileSync(cssPath, "utf8");
  const hasRemoteImport = /@import\s+url\(["']?https?:\/\//i.test(css);
  const hasMaxZIndex = /z-index:\s*(9999|2147483647)\b/.test(css);
  recordCheck(`${rel}: cero @import remotos`, !hasRemoteImport);
  recordCheck(`${rel}: escala z-index disciplinada`, !hasMaxZIndex);
}

// 3. Contraste WCAG 2.2 AA sobre paleta canónica y Workspace
const contrastPairs = [
  ["Canon texto principal (#f5f2eb sobre #05030a)", "#f5f2eb", "#05030a", 4.5],
  ["Canon texto secundario (#b8b4ac sobre #05030a)", "#b8b4ac", "#05030a", 4.5],
  ["Canon señal cian (#4de8e0 sobre #05030a)", "#4de8e0", "#05030a", 4.5],
  ["Canon dorado (#d4af37 sobre #05030a)", "#d4af37", "#05030a", 4.5],
  [
    "Workspace texto secundario (#a6b4c6 sobre #0e131d)",
    "#a6b4c6",
    "#0e131d",
    4.5,
  ],
  ["Workspace placeholder (#8ea0b5 sobre #080d15)", "#8ea0b5", "#080d15", 4.5],
  ["Botón primario (#05030a sobre #4de8e0)", "#05030a", "#4de8e0", 4.5],
  [
    "Editorial texto secundario (#595651 sobre #f7f4ef)",
    "#595651",
    "#f7f4ef",
    4.5,
  ],
  [
    "Editorial tarjeta secundaria (#595651 sobre #f1eee9)",
    "#595651",
    "#f1eee9",
    4.5,
  ],
  ["Editorial acento (#8c3d22 sobre #f7f4ef)", "#8c3d22", "#f7f4ef", 4.5],
];

const contrastResults = contrastPairs.map(([label, fg, bg, minRatio]) => {
  const ratio = contrastRatio(fg, bg);
  const ok = ratio >= minRatio;
  recordCheck(`WCAG AA ${label}`, ok, `${ratio}:1 (mín ${minRatio}:1)`);
  return { label, fg, bg, ratio, minRatio, ok };
});

// 4. Auditoría de Capa WebGL / GPU
for (const gpuRel of ["hero.js", "src/components/HeroShader.tsx"]) {
  const src = readFileSync(join(ROOT, gpuRel), "utf8");
  recordCheck(
    `${gpuRel}: respeta prefers-reduced-motion`,
    src.includes("prefers-reduced-motion"),
  );
  recordCheck(
    `${gpuRel}: pausa en visibilitychange`,
    src.includes("visibilitychange") && src.includes("cancelAnimationFrame"),
  );
  recordCheck(
    `${gpuRel}: degradación elegante Canvas 2D / CSS`,
    src.includes('getContext("2d")') || src.includes("canvas2d"),
  );
  recordCheck(`${gpuRel}: sin bug GLSL p.z sobre vec2`, !/\bp\.z\b/.test(src));
}

// 5. Presupuesto de rendimiento en dist/
const distMetrics = {
  present: false,
  files: [],
  totals: { rawBytes: 0, gzipBytes: 0 },
};

const distDir = join(ROOT, "dist");
if (!args.has("--no-dist") && existsSync(distDir)) {
  distMetrics.present = true;
  const distHtmlFiles = walkFilesByExt(distDir, ".html", new Set());
  recordCheck(
    `dist/: compila todas las entradas HTML (${distHtmlFiles.length}/${sourceHtmlFiles.length})`,
    distHtmlFiles.length === sourceHtmlFiles.length,
    `dist=${distHtmlFiles.length}, fuente=${sourceHtmlFiles.length}`,
  );

  for (const distHtmlPath of distHtmlFiles) {
    const relDist = distHtmlPath.slice(distDir.length + 1);
    const domDist = new JSDOM(readFileSync(distHtmlPath, "utf8"));
    const brokenInDist = [];
    for (const el of domDist.window.document.querySelectorAll("[href], [src]")) {
      const val = (el.getAttribute("href") || el.getAttribute("src") || "").trim();
      if (!val || val.startsWith("#") || URI_SCHEME_RE.test(val)) continue;
      const cleanRel = val.split("#")[0].split("?")[0];
      if (!cleanRel) continue;
      const candidate = cleanRel.startsWith("/")
        ? join(distDir, cleanRel.slice(1))
        : resolve(dirname(distHtmlPath), cleanRel);
      if (!existsSync(candidate)) {
        brokenInDist.push(val);
      }
    }
    recordCheck(
      `dist/${relDist}: activos y enlaces compilados existen`,
      brokenInDist.length === 0,
      brokenInDist.join(", "),
    );
  }

  const distAssets = join(distDir, "assets");
  const inspectTargets = [
    join(distDir, "index.html"),
    join(distDir, "workspace.html"),
    ...(existsSync(distAssets)
      ? readdirSync(distAssets)
          .filter((n) => [".js", ".css"].includes(extname(n)))
          .map((n) => join(distAssets, n))
      : []),
  ];

  for (const target of inspectTargets) {
    if (!existsSync(target) || !statSync(target).isFile()) continue;
    const buf = readFileSync(target);
    const gz = gzipSync(buf);
    const rel = target.slice(distDir.length + 1);
    distMetrics.files.push({
      file: rel,
      rawBytes: buf.length,
      gzipBytes: gz.length,
    });
    distMetrics.totals.rawBytes += buf.length;
    distMetrics.totals.gzipBytes += gz.length;

    if (rel === "index.html") {
      recordCheck(
        "Presupuesto dist/index.html gzip <= 15 KB",
        gz.length <= 15 * 1024,
        `${(gz.length / 1024).toFixed(2)} KB`,
      );
    }
    if (rel.startsWith("assets/workspace-") && rel.endsWith(".js")) {
      recordCheck(
        "Presupuesto chunk app workspace JS gzip <= 25 KB",
        gz.length <= 25 * 1024,
        `${(gz.length / 1024).toFixed(2)} KB`,
      );
    }
    if (rel.endsWith(".css")) {
      recordCheck(
        `Presupuesto CSS ${rel} gzip <= 10 KB`,
        gz.length <= 10 * 1024,
        `${(gz.length / 1024).toFixed(2)} KB`,
      );
    }
  }
}

const passed = checks.filter((c) => c.ok).length;
const score = Math.round((passed / Math.max(1, checks.length)) * 100);

const report = {
  ok: errors.length === 0,
  score,
  passed,
  total: checks.length,
  htmlFilesAudited: sourceHtmlFiles.length,
  contrast: contrastResults,
  dist: distMetrics,
  errors,
};

if (args.has("--json")) {
  console.log(JSON.stringify(report, null, 2));
} else {
  console.log(
    `audit-web: ${passed}/${checks.length} comprobaciones superadas (índice ${score}/100) · ${sourceHtmlFiles.length} archivos HTML auditados`,
  );
  if (distMetrics.present) {
    console.log(
      `bundle dist/ auditado: ${(distMetrics.totals.rawBytes / 1024).toFixed(2)} KB raw · ${(distMetrics.totals.gzipBytes / 1024).toFixed(2)} KB gzip`,
    );
  }
  for (const err of errors) {
    console.error(`  FALLA: ${err}`);
  }
}

process.exit(errors.length === 0 ? 0 : 1);
