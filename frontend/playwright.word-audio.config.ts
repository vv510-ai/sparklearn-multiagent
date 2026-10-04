import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  webServer: Array.isArray(base.webServer)
    ? base.webServer.map(server => ({ ...server, command: server.command.replace("next dev -p", "next dev --webpack -p") }))
    : base.webServer,
  testMatch: "word-audio.spec.ts",
  use: { ...base.use, video: "off" },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"], launchOptions: { args: ["--autoplay-policy=user-gesture-required"], ignoreDefaultArgs: ["--mute-audio"] } } },
    { name: "android-chromium", use: { ...devices["Pixel 7"], launchOptions: { args: ["--autoplay-policy=user-gesture-required"], ignoreDefaultArgs: ["--mute-audio"] } } },
    { name: "iphone-webkit", use: { ...devices["iPhone 13"], browserName: "webkit" } },
    { name: "desktop-firefox", use: { ...devices["Desktop Firefox"] } },
  ],
});
