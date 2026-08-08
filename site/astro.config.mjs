import { defineConfig } from "astro/config";
import { fileURLToPath } from "node:url";

const docsDirectories = ["../research", "../reference"].map((directory) =>
  fileURLToPath(new URL(directory, import.meta.url)),
);

const watchRepositoryDocs = {
  name: "watch-repository-docs",
  configureServer(server) {
    server.watcher.add(docsDirectories);
  },
  handleHotUpdate({ file, server }) {
    if (!docsDirectories.some((directory) => file.startsWith(`${directory}/`))) return;
    server.moduleGraph.invalidateAll();
    server.ws.send({ type: "full-reload" });
    return [];
  },
};

export default defineConfig({
  site: "https://windgrams.azohra.com",
  vite: {
    plugins: [watchRepositoryDocs],
    server: { fs: { allow: [".."] } },
  },
  // The old chart entry point now opens the model-selection article.
  redirects: {
    "/chart/": "/research/choosing-forecast-models/",
    "/research/": "/",
  },
});
