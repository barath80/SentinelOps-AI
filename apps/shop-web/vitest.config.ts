import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    setupFiles: ["src/test/setup.ts", "src/test/fakeDb.ts"],
    coverage: {
      provider: "v8",
      include: ["src/lib/**", "src/app/api/**"],
    },
  },
});
