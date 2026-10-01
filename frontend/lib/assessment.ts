export type StudySurvey = {
  notebook_id?: string;
  course_key?: "ds_algo" | "python" | "calculus" | "cet6" | "english" | "custom";
  course_title?: string;
  source_ids?: string[];
  course_revision?: string;
  target_kps?: string[] | null;
  daily_minutes: number;
  study_days: number[];
  goal: string;
  stage: string;
  prior_experience: string;
  pressure: "normal" | "high" | "skip";
  study_habit: "reread" | "practice" | "mixed" | "skip";
  support: string;
  target_date: string | null;
  goals?: string[];
  barriers?: string[];
  supports?: string[];
  study_cue?: string;
  materials_status?: "已有资料" | "暂时没有" | "稍后上传";
  intro_practiced?: boolean;
};
export type StudyTask = {
  id: string;
  kp: string;
  title: string;
  kind: "diagnose" | "transfer" | "study" | "review";
  minutes: number;
  done: boolean;
  requires: string[];
  reason: string;
  goal: string;
  criterion: string;
  deferred_reason?: string;
  steps?: string[];
  readings?: { title: string; url: string; version: string }[];
};
export type Assessment = {
  notebook_id?: string;
  course?: CourseScope | null;
  id: string;
  revision: number;
  status: "active" | "completed";
  mode: "screening" | "comprehensive" | "foundation";
  answered: number;
  maximum: number;
  survey: StudySurvey;
  bank_version: string;
  question: {
    id: string;
    stem: string;
    options: string[];
    topic: string;
    type: "single" | "multiple";
    audio_url?: string;
    instruction?: string;
  } | null;
  report: null | {
    coverage: number;
    total_skills: number;
    boundary: string;
    calibration_samples: number;
    calibration_error: number | null;
    skills: {
      kp: string;
      name: string;
      attempts: number;
      correct: number;
      accuracy: number | null;
      status: "unmeasured" | "gap" | "developing" | "strength";
      label: string;
      high_confidence_errors: number;
      in_scope?: boolean;
      after_intro?: boolean;
    }[];
    explanations: {
      id: string;
      kp: string;
      stem: string;
      correct: boolean;
      status: string;
      answer: string;
      explain: string;
      options?: string[];
      learner_answer?: string;
      topic?: string;
      instruction?: string;
      audio_url?: string;
    }[];
  };
  plan: null | {
    days: {
      date: string;
      capacity: number;
      minutes: number;
      tasks: StudyTask[];
    }[];
    deferred: StudyTask[];
    rule: string;
    support: string;
    goal: string;
    reflection: string;
    adaptations?: string[];
    practice_update?: string;
  };
  materials: { id: string; kp: string; title: string; markdown: string }[];
  learning_progress?: Record<string, PracticeProgress>;
};

export type PracticeResult = {
  transcript?: string | null;
  question_id: string; choice: string | null; assisted: boolean; correct: boolean;
  independent: boolean; answer: string; explain: string; message: string;
  citations: { source: string; chapter: string; url: string; version: string }[];
};
export type PracticeProgress = {
  answered?: number; independent?: number; correct?: number; next_due_at?: string | null;
  exhausted?: boolean; last_result?: PracticeResult;
};
export type Textbook = {
  source_note?: string;
  id: string; title: string; version: string; url: string; license: string; license_url: string;
  scope_note: string; sha256: string;
  sections: { id: string; title: string; url: string; kps: string[]; sha256: string }[];
};

export type CourseScope = {
  study_path?: import("./course-study").StudyPathSummary | null;
  source_policy?: string;
  exam_reference?: { url: string; checked_on: string; total_minutes: number; parts: { name: string; weight: number; minutes: number }[] } | null;
  title: string;
  kind: string;
  revision: string;
  source_ids: string[];
  sources: { id: string; title: string; sha256: string; sampled_chunks: number; total_chunks: number; location_kind: string; locations: number[] }[];
  outline: { id: string; name: string; objective: string }[];
  question_count: number;
  boundary: string;
  coverage_note: string;
  textbook?: Textbook | null;
  practice_available?: boolean;
};

export function downloadMarkdown(title: string, markdown: string) {
  const url = URL.createObjectURL(
    new Blob([markdown], { type: "text/markdown;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `${title.replace(/[\\/:*?"<>|]/g, "-")}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
