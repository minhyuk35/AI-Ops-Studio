import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The monorepo keeps one .env at the repo root; without this, Vite's
  // default envDir (this package's own folder) never sees it and every
  // VITE_* var silently resolves to undefined.
  envDir: "../..",
  build: {
    rollupOptions: {
      output: {
        // 자주 안 바뀌는 벤더 라이브러리를 앱 코드와 분리 -- 앱 코드만 바뀐
        // 배포에서 사용자가 이 청크들을 다시 받지 않아도 되게(브라우저 캐시 재사용).
        manualChunks: {
          "vendor-react": ["react", "react-dom", "@tanstack/react-query"],
          "vendor-gsap": ["gsap"],
          "vendor-markdown": ["react-markdown"],
        },
      },
    },
  },
});
