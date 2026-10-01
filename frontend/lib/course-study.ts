export type StudyUnitSummary = { id: string; group: string; title: string };
export type StudyPathSummary = { course: string; title: string; subtitle: string; version: string; units: StudyUnitSummary[] };
export type StudyUnit = StudyUnitSummary & { material_id: string; location: string; task: string; check: string; minutes: number;
  source: { title: string; url: string; source_role: string; provider: string; access: string; verification: string; scope: string };
  excerpts: { id: string; title: string; text: string; url: string; version: string; license: string; license_url: string }[] };
export type UnitRecord = { read: boolean; practiced: boolean; checked: boolean; completed: boolean; notes: string; next_review: string | null };
export type StudyProgress = { revision: number; last_unit: string; units: Record<string, UnitRecord> };
export type CourseStudy = { notebook_id: string; path: StudyPathSummary & { units: StudyUnit[] }; progress: StudyProgress };
