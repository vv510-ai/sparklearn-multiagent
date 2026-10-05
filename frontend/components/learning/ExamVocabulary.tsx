"use client";

import { useState } from "react";
import type { ExamVocabularyHint } from "@/lib/cet6-exams";
import WordLesson from "./WordLesson";

export default function ExamVocabulary({ notebookId, questionNumber, hints, onLocate }: {
  notebookId: string; paperId: string; questionNumber: number; hints: ExamVocabularyHint[]; onLocate: () => void;
}) {
  const [selected, setSelected] = useState<ExamVocabularyHint | null>(null);
  return <section className="exam-vocabulary" aria-label={`第 ${questionNumber} 题词汇`}>
    <h4>读懂本题的词</h4>
    <div className="exam-actions">{hints.map(h => <button key={h.sense_id} aria-pressed={selected?.sense_id === h.sense_id}
      onClick={() => setSelected(selected?.sense_id === h.sense_id ? null : h)}>{h.word}</button>)}</div>
    {selected && <div key={selected.sense_id}>
      <p>{selected.meaning}</p>
      <button className="exam-context-link" onClick={onLocate}>回到原文点词，保留原句</button>
      <WordLesson notebookId={notebookId} wordId={selected.word_id} senseId={selected.sense_id} />
    </div>}
  </section>;
}
