export type StudySurvey = {
  daily_minutes: number;
  study_days: number[];
  goal: string;
  stage: string;
  prior_experience: string;
  pressure: "normal" | "high" | "skip";
  study_habit: "reread" | "practice" | "mixed" | "skip";
  support: string;
  target_date: string | null;
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
};
export type Assessment = {
  id: string;
  revision: number;
  status: "active" | "completed";
  mode: "comprehensive" | "foundation";
  answered: number;
  maximum: number;
  survey: StudySurvey;
  bank_version: string;
  question: {
    id: string;
    stem: string;
    options: string[];
    topic: string;
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
    }[];
    explanations: {
      id: string;
      kp: string;
      stem: string;
      correct: boolean;
      status: string;
      answer: string;
      explain: string;
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
  };
  materials: { id: string; kp: string; title: string; markdown: string }[];
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
