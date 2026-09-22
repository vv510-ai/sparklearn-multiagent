/** SparkLearn 前后端事件协议(与 backend/app/agents/emitter.py 对齐)。 */
export type AgentId =
  | "profile" | "orchestrator" | "planner" | "path"
  | "doc" | "mindmap" | "quiz" | "media" | "tutor" | "eval";

export interface SparkEvent {
  type:
    | "agent_start" | "agent_end" | "agent_token"
    | "token" | "resource" | "profile" | "path"
    | "progress" | "citations" | "safety" | "summary" | "trace"
    | "conversation_cleared" | "error" | "done";
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
  text?: string;
  percent?: number;
  stage?: string;
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
  messages?: { role: "user" | "assistant"; content: string }[];
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
    template?: string;
    notes_scope?: string;
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
    one_page_visual?: {
      pages?: { title: string; image_url?: string; provider?: string; model?: string; image_status?: string; image_error?: string; center?: string; nodes?: { label: string; text: string }[]; steps?: string[] }[];
      model?: string;
      title?: string;
      center?: string;
      nodes?: { label: string; text: string }[];
      steps?: string[];
      image_url?: string;
      provider?: string;
      image_status?: "ready" | "fallback" | string;
      image_error?: string;
    };
    difficulty?: number;
    script?: { title?: string; narration?: string; scenes?: { t: string; visual: string; caption?: string }[]; video_prompt?: string; target_seconds?: number; video_clip_seconds?: number };
    video?: {
      status?: string;
      url?: string;
      task_id?: string;
      error?: string;
      reason?: string;
      retryable?: boolean;
      stored?: boolean;
      cached?: boolean;
      phase?: string;
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
