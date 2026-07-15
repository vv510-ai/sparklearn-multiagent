/** SparkLearn 前后端事件协议(与 backend/app/agents/emitter.py 对齐)。 */
export type AgentId =
  | "profile" | "orchestrator" | "planner" | "path"
  | "doc" | "mindmap" | "quiz" | "media" | "tutor" | "eval";

export interface SparkEvent {
  type:
    | "agent_start" | "agent_end" | "agent_token"
    | "token" | "resource" | "profile" | "path"
    | "progress" | "citations" | "safety" | "summary" | "trace"
    | "error" | "done";
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
    markmap?: string;
    questions?: QuizQuestion[];
    difficulty?: number;
    script?: { title?: string; narration?: string; scenes?: { t: string; visual: string; caption?: string }[]; video_prompt?: string };
    video?: { status?: string; url?: string; task_id?: string; error?: string; reason?: string };
    manim_code?: string;
    audio_url?: string;
    audio_narration?: string;
    audio?: {
      status?: "ready" | "fallback" | "blocked" | string;
      provider?: "spark_tts" | "browser_speech" | "none" | string;
      error?: string;
      retryable?: boolean;
    };
    cover_url?: string;
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
  knowledge_mastery: Record<string, number>;
  cognitive_style: string;
  error_prone: string[];
  goal: string;
  pace: { daily_minutes?: number; frequency?: string; focus?: string } | string;
  difficulty_pref: string;
  resource_pref: Record<string, number>;
  metacognition: number | string;
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
  order?: number;
}

export interface PathPlan {
  nodes: PathNode[];
  edges: { from: string; to: string }[];
  next_kp: string | null;
  generated_by?: string;
  updated_at?: string;
  remediation?: LearningDiagnosis;
}
