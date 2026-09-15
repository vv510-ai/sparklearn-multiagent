export function voiceLabel(audio?: { provider?: string; model?: string }): string {
  if (audio?.provider === "elevenlabs") return "ElevenLabs · AI 合成语音";
  if (audio?.provider === "openai") return "OpenAI · AI 合成语音";
  if (audio?.provider === "spark_super_tts") return "星火超拟人 · AI 合成语音";
  if (audio?.provider === "spark_tts") return "星火 · AI 合成语音";
  return "AI 合成语音讲解";
}
