import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    target: "es2022",
    sourcemap: false,
    rollupOptions: {
      input: { landing: "index.html", workspace: "workspace.html" },
    },
  },
  server: {
    host: "0.0.0.0",
  },
  preview: {
    host: "0.0.0.0",
  },
});
