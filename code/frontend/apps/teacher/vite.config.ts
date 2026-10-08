// 개발 중엔 /api·/images 를 FastAPI(8000) 로 넘긴다 (같은 출처처럼 보여 쿠키가 그대로 간다).
// 빌드 결과(dist/)는 FastAPI 가 /app/teacher/ 아래에서 서빙한다 (serve/api.py spa).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  base: "/app/teacher/",
  resolve: { alias: { "@pl/shared": fileURLToPath(new URL("../../packages/shared/src/index.ts", import.meta.url)) } },
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/images": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", emptyOutDir: true },
});
