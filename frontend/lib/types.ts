/** SparkLearn 前后端事件协议(与 backend/app/agents/emitter.py 对齐)。 */
export type AgentId =
  | "profile" | "orchestrator" | "planner" | "path"
  | "doc" | "mindmap" | "quiz" | "media" | "music" | "tutor" | "eval";

export interface OnePageImage {
  index: number;
  url: string;
  title?: string;
  width?: number;
  height?: number;
  transcript?: string;
  verification?: {
    status: "passed" | "failed" | "unverified";
    checks?: Record<string, string>;
    issues: string[];
  };
}

export interface SongVersion {
  song_id: string;
  title?: string;
  audio_url?: string;
  cover_url?: string;
  duration?: number;
  status?: string;
  timeline?: { text: string; start: number; end: number }[];
}

export interface SongPayload {
  status: "ready" | "failed" | "blocked" | "lyrics_only" | string;
  topic?: string;
  title?: string;
  mnemonic?: { line: string; meaning: string }[];
  plan?: {
    genre?: string;
    style_tags?: string;
    bpm?: number;
    mood?: string;
    vocal_gender?: string;
    reason?: string;
    structure?: string[];
  };
  lyrics?: string;
  cloze?: { line: string; answer: string }[];
  review?: { status: string; issues: string[] };
  versions?: SongVersion[];
  provider?: string;
  model?: string;
  error?: string;
}

export interface OnePageVisualData {
  title?: string;
  image_url?: string;
  images?: OnePageImage[];
  prompt_mode?: "simple" | "draft";
  conversation_url?: string;
  coverage?: { status: string; missing: string[] };
  provider?: string;
  model?: string;
  renderer?: string;
  layout?: "knowledge_map" | "text_excerpt";
  relation_count?: number;
  content_status?: string;
  image_status?: string;
  image_error?: string;
  center?: string;
  nodes?: { label: string; text: string }[];
  steps?: string[];
  pages?: OnePageVisualData[];
  generation_attempts?: number;
  verification?: {
    status: "passed" | "failed" | "unverified";
    checks?: { text: string; formulas: string; relations: string };
    issues: string[];
  };
}

export interface SourceEvidence {
  index: number;
  citation: string;
  source_id?: string;
  source?: string;
  chapter?: string;
  page?: number;
  location_kind?: string;
  preview?: string;
  excerpt?: string;
}

export interface SparkEvent {
  job_id?: string;
  reset?: boolean;
  event_id?: number;
  status?: string;
  type:
    | "agent_start" | "agent_end" | "agent_token"
    | "token" | "resource" | "profile" | "path"
    | "progress" | "citations" | "safety" | "summary" | "trace"
    | "conversation_cleared" | "error" | "job" | "done";
  ts?: string;
  agent?: AgentId | string;
  label?: string;
  detail?: string;
  summary?: string;
  delta?: string;
  resource?: ResourceItem;
  profile?: StudentProfile;
  path?: PathPlan;
  items?: string[];
  evidence?: SourceEvidence[];
  text?: string;
  percent?: number;
  stage?: string;
  model_route?: { model: string; provider: string; automatic: boolean; reason: string };
  level?: string;
  output?: Record<string, unknown>;
  session_id?: string;
  run_dir?: string;
  [k: string]: unknown;
}

export interface LearningNotebook {
  id: string;
  user_id: string;
  title: string;
  emoji: string;
  session_id: string;
  source_count: number;
  message_count: number;
  created_at: string;
  updated_at: string;
  messages?: { role: "user" | "assistant"; content: string; source_evidence?: SourceEvidence[] }[];
}

export interface QuizQuestion {
  id: string;
  type: "single" | "fill" | "judge" | "design" | "complexity";
  stem: string;
  options: string[];
  answer: string;
  explain?: string;
  kp: string;
  difficulty: number;
  error_tags: string[];
}

export interface ResourceItem {
  id: string;
  kind: "doc" | "code" | "reading" | "mindmap" | "quiz" | "video" | string;
  kp: string;
  title: string;
  payload: {
    markdown?: string;
    source_evidence?: SourceEvidence[];
    verification?: string;
    generation_details?: { status: string; reason_codes: string[]; message: string };
    generation_mode?: "unavailable" | "demo" | "source_guide" | "model";
    template?: string;
    notes_scope?: string;
    source_policy?: "strict" | "supplement";
    markmap?: string;
    questions?: QuizQuestion[];
    flashcards?: {
      title?: string;
      blocked?: boolean;
      blocked_reason?: string;
      cards?: { id: string; front: string; back: string; hint?: string; source_index?: number | null }[];
    };
    infographic?: {
      title?: string;
      summary?: string;
      blocked?: boolean;
      blocked_reason?: string;
      sections?: { title: string; body: string; source_index?: number | null }[];
      steps?: string[];
    };
    data_table?: {
      title?: string;
      blocked?: boolean;
      blocked_reason?: string;
      columns?: string[];
      rows?: string[][];
    };
    one_page_visual?: OnePageVisualData;
    difficulty?: number;
    script?: { title?: string; narration?: string; scenes?: { t: string; visual: string; caption?: string }[]; video_prompt?: string; target_seconds?: number; video_clip_seconds?: number };
    song?: SongPayload;
    video?: {
      status?: string;
      url?: string;
      poster_url?: string;
      duration?: number;
      width?: number;
      height?: number;
      engine?: string;
      model?: string;
      provider?: string;
      task_id?: string;
      error?: string;
      reason?: string;
      retryable?: boolean;
      stored?: boolean;
      cached?: boolean;
      phase?: string;
      /** Claude Code videos (provider "claude_code"): live state from the local worker. */
      message?: string;
      progress?: number;
      effort?: string;
      code?: string;
      title?: string;
      notes?: string;
      approve_storyboard?: boolean;
      worker_online?: boolean;
      storyboard?: VideoStoryboard | null;
      chapters?: { start: number; title: string }[];
    };
    manim_code?: string;
    python_code?: string;
    animation_mode?: "video" | "manim" | "python_animation" | string;
    animation_preview?: {
      title?: string;
      interval_ms?: number;
      stages?: { label: string; detail: string; time?: string }[];
    };
    audio_url?: string;
    audio_narration?: string;
    audio?: {
      model?: string;
      ai_generated?: boolean;
      status?: "ready" | "fallback" | "blocked" | string;
      provider?: "spark_tts" | "browser_speech" | "none" | string;
      error?: string;
      retryable?: boolean;
      degraded?: boolean;
      strict_voice?: boolean;
    };
    cover_url?: string;
    ppt?: {
      model?: string;
      status?: "building" | "ready" | "failed" | "blocked" | string;
      task_id?: string;
      url?: string;
      title?: string;
      subtitle?: string;
      cover_url?: string;
      total_pages?: number;
      done_pages?: number;
      provider_status?: string;
      image_status?: string;
      provider?: string;
      error?: string;
      retryable?: boolean;
    };
    explicit_only?: boolean;
    source_bound?: boolean;
    grounded?: boolean;
    remediation?: {
      origin_attempt_id?: number;
      blocked_kp?: string;
      prerequisite_gap?: string | null;
      misconception?: string;
      next_action?: string;
    };
  };
  citations: string[];
  created_at?: string;
}

export interface LearningDiagnosis {
  status: "clear" | "needed";
  action: "advance" | "remediate" | "reteach" | "schedule_review" | "review_again";
  phase: "initial" | "retest" | "spaced_review" | string;
  attempt: number;
  max_attempts: number;
  blocked_kp?: string | null;
  blocked_name?: string;
  prerequisite_gap?: string | null;
  prerequisite_name?: string;
  prerequisite_mastery?: number | null;
  remediation_kp?: string | null;
  remediation_name?: string;
  misconception?: string;
  severity: "none" | "medium" | "high" | string;
  evidence: string[];
  reason: string;
}

export interface StudentProfile {
  notebook_id?: string;
  course_title?: string;
  knowledge_labels?: Record<string, string>;
  learning_intake?: import("./assessment").StudySurvey;
  knowledge_mastery: Record<string, number>;
  cognitive_style: string;
  error_prone: string[];
  goal: string;
  pace: { daily_minutes?: number; weekly_minutes?: number; frequency?: string; focus?: string } | string;
  difficulty_pref: string;
  resource_pref: Record<string, number>;
  metacognition: number | string;
  focus_kps?: string[];
  learning_topic?: string;
  current_level?: string;
  materials_status?: string;
  onboarding_completed?: boolean;
  version?: number;
  _version?: number;
  _updated_at?: string;
}

export interface PathNode {
  id: string;
  name: string;
  mastery: number;
  status: "done" | "ready" | "locked";
  difficulty: number;
  score: number;
  reason: string;
  chapter?: string;
  desc?: string;
  order?: number;
  subtopics?: PathSubtopic[];
}

export interface PathSubtopic {
  id: string;
  name: string;
  relation?: string;
  desc?: string;
}

export interface PathPlan {
  course?: string;
  course_id?: string;
  graph_version?: number;
  nodes: PathNode[];
  edges: { from: string; to: string }[];
  detail_edges?: { from: string; to: string; label?: string }[];
  next_kp: string | null;
  generated_by?: string;
  updated_at?: string;
  remediation?: LearningDiagnosis;
}

export interface VideoStoryboardScene {
  title: string;
  goal?: string;
  narration: string;
  visual?: string;
  on_screen?: string[];
  transition?: string;
  start?: number;
  end?: number;
}

export interface VideoStoryboard {
  title: string;
  hook?: string;
  summary?: string;
  visual_style?: string;
  quiz?: string;
  self_check?: string;
  duration?: number;
  scenes: VideoStoryboardScene[];
}

export interface ClaudeVideoOption { id: string; label: string; note: string }

export interface ClaudeVideoSettings {
  available: boolean;
  reason: string;
  note: string;
  active_jobs: number;
  config: {
    model: string; effort: string; engine: string; max_seconds: number; voice: string; quality: string;
    approve_storyboard: boolean; access: "subscription" | "api_key"; budget_usd: number;
    has_api_key: boolean; revision: number;
  };
  options: {
    models: ClaudeVideoOption[]; efforts: ClaudeVideoOption[]; engines: ClaudeVideoOption[];
    voices: ClaudeVideoOption[]; qualities: ClaudeVideoOption[]; durations: number[];
  };
  worker: {
    online: boolean; last_seen: number | null; cli_version: string; busy: boolean;
    auth: { logged_in: boolean; method: string; plan: string };
    tools: Record<string, string>;
  };
  test: { status: string; reply: string; detail: string; model: string; at: number } | null;
}
