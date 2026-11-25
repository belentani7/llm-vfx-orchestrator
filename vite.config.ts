import { cpSync, existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

function copyStaticStudioAssets(): Plugin {
  const staticPaths = [
    "hero.js",
    "hero.css",
    "manifest.webmanifest",
    "robots.txt",
    "sitemap.xml",
    "assets",
    "brand",
    "_shared",
  ];

  return {
    name: "copy-static-studio-assets",
    closeBundle() {
      const outRoot = resolve(__dirname, "dist");
      mkdirSync(outRoot, { recursive: true });
      for (const rel of staticPaths) {
        const src = resolve(__dirname, rel);
        if (!existsSync(src)) continue;
        const dest = resolve(outRoot, rel);
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
        main: resolve(__dirname, "index.html"),
        workspace: resolve(__dirname, "workspace.html"),
        docs: resolve(__dirname, "docs.html"),
        ecosistema: resolve(__dirname, "ecosistema.html"),
        ampliacion: resolve(__dirname, "ampliacion.html"),
        accesibilidad: resolve(__dirname, "accesibilidad.html"),
        accessibility: resolve(__dirname, "accessibility.html"),
        privacidad: resolve(__dirname, "privacidad.html"),
        avisoLegal: resolve(__dirname, "aviso-legal.html"),
        notFound: resolve(__dirname, "404.html"),
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
