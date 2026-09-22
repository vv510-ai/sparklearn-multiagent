import { defineConfig, devices } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const backendPort = 18000;
const frontendPort = 13000;
const repoRoot = path.resolve(__dirname, "..");
const backendDir = path.join(repoRoot, "backend");
const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL?.trim();
const inheritedEnv = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
);
const runDir = path.join(repoRoot, ".tmp", "playwright", String(process.pid));
const databasePath = path.join(runDir, "sparklearn-e2e.db").replaceAll("\\", "/");
const pythonExecutable = process.env.PLAYWRIGHT_PYTHON?.trim()
  || path.join(backendDir, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

mkdirSync(runDir, { recursive: true });

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 90_000 },
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  outputDir: "test-results",
  use: {
    baseURL: externalBaseURL || `http://localhost:${frontendPort}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: externalBaseURL ? undefined : [
    {
      command: `"${pythonExecutable}" -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${backendPort}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...inheritedEnv,
        DATABASE_URL: `sqlite:///${databasePath}`,
        DEMO_MODE: "true",
        AUTH_REQUIRED: "true",
        AUTH_SECRET: "playwright-local-only-0123456789-abcdefghijklmnopqrstuvwxyz",
        SPARK_API_PASSWORD: "",
        DEEPSEEK_API_KEY: "",
        OPENAI_API_KEY: "",
        KIMI_API_KEY: "",
        LLM_PROVIDER: "spark",
        KIMI_SMART_ROUTING: "false",
      },
    },
    {
      command: process.env.PLAYWRIGHT_PRODUCTION === "true"
        ? "node node_modules/next/dist/bin/next start -p 13000"
        : "npm run dev:e2e",
      cwd: __dirname,
      url: `http://localhost:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...inheritedEnv,
        BACKEND_URL: `http://127.0.0.1:${backendPort}`,
      },
    },
  ],
});
