import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

const ROOT = import.meta.dirname;

function copyStaticStudioAssets(): Plugin {
  const staticPaths = [
    "hero.js",
    "hero.css",
    "manifest.webmanifest",
    "robots.txt",
    "sitemap.xml",
    "assets",
    "brand",
    "docs/site.js",
  ];

  return {
    name: "copy-static-studio-assets",
    closeBundle() {
      const outRoot = resolve(ROOT, "dist");
      mkdirSync(outRoot, { recursive: true });
      for (const rel of staticPaths) {
        const src = resolve(ROOT, rel);
        if (!existsSync(src)) continue;
        const dest = resolve(outRoot, rel);
        mkdirSync(dirname(dest), { recursive: true });
        cpSync(src, dest, { recursive: true });
      }
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [copyStaticStudioAssets()],
  server: {
    host: "0.0.0.0",
    allowedHosts: true,
  },
  preview: {
    host: "0.0.0.0",
    allowedHosts: true,
  },
  build: {
    target: "es2022",
    rollupOptions: {
      input: {
        main: resolve(ROOT, "index.html"),
        workspace: resolve(ROOT, "workspace.html"),
        docs: resolve(ROOT, "docs.html"),
        ecosistema: resolve(ROOT, "ecosistema.html"),
        ampliacion: resolve(ROOT, "ampliacion.html"),
        accesibilidad: resolve(ROOT, "accesibilidad.html"),
        accessibility: resolve(ROOT, "accessibility.html"),
        privacidad: resolve(ROOT, "privacidad.html"),
        avisoLegal: resolve(ROOT, "aviso-legal.html"),
        notFound: resolve(ROOT, "404.html"),
        docsPortal: resolve(ROOT, "docs/index.html"),
        siteIndex: resolve(ROOT, "site/index.html"),
        magicImmersive: resolve(ROOT, "magic/immersive.html"),
        magicSfx: resolve(ROOT, "magic/sfx.html"),
        magicShader: resolve(ROOT, "magic/shader.html"),
        plataformaPrototipo: resolve(ROOT, "plataforma/PROTOTIPO.html"),
        productoLanding: resolve(ROOT, "producto/landing.html"),
      },
      output: {
        manualChunks(id) {
          if (
            id.includes("node_modules/react") ||
            id.includes("node_modules/scheduler")
          ) {
            return "vendor-react";
          }
          return undefined;
        },
      },
    },
  },
});
