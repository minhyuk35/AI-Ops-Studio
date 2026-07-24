import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The monorepo keeps one .env at the repo root; without this, Vite's
  // default envDir (this package's own folder) never sees it and every
  // VITE_* var silently resolves to undefined.
  envDir: "../..",
});
