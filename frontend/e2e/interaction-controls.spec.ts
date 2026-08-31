import { expect, test } from "@playwright/test";
import { isInteractiveAudioResource } from "../components/resource/interaction";

test("只有互动讲解资源允许播放中快捷提问", () => {
  expect(isInteractiveAudioResource({
    kind: "doc",
    payload: { template: "complete_notes", audio_url: "/static/gen/notes.mp3" },
  })).toBe(false);

  expect(isInteractiveAudioResource({
    kind: "doc",
    payload: { template: "interactive_audio", audio_url: "/static/gen/interactive.mp3" },
  })).toBe(true);

  expect(isInteractiveAudioResource({
    kind: "video",
    payload: { template: "interactive_audio", audio_url: "/static/gen/video.mp3" },
  })).toBe(false);
});
