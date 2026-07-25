import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The monorepo keeps one .env at the repo root; without this, Vite's
  // default envDir (this package's own folder) never sees it and every
  // VITE_* var silently resolves to undefined.
  envDir: "../..",
  // Served from /console/ in production (see root vercel.json -- this
  // build's dist/ gets copied under demo-store's dist/console/). Without
  // this, the built HTML references /assets/... instead of
  // /console/assets/..., which 404s once it's not at the site root.
  base: "/console/",
});
