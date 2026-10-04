"use client";

import type { WordCard } from "@/lib/cet6";
import "./exam-reading-tools.css";

export default function WordContexts({ notebookId, contexts, revealed = true }: { notebookId: string; contexts: WordCard["contexts"]; revealed?: boolean }) {
  if (!contexts.length) return null;
  const items = revealed ? contexts : contexts.slice(-1);
  return <section className="word-context-recall" aria-label="原句复习">
    <strong>{revealed ? "原句与出处" : "联系原句，回忆这个词的意思"}</strong>
    {items.map((c, i) => <article key={i}><blockquote lang="en">{c.text}</blockquote>{revealed && <>
      {c.note && <p>我的语境理解：{c.note}</p>}<p>{c.source}</p>
      {c.question_prompt && <p>第 {c.question_number} 题：{c.question_prompt}</p>}
      {c.exam_id && <a href={`/?${new URLSearchParams({ notebook: notebookId, cet6: "exams", exam_paper: c.exam_id, exam_kind: c.exam_kind || "reading_careful", exam_question: String(c.exam_question || 46) })}`}>回到原题 · 第 {c.exam_question} 题</a>}
      {c.reading_id && <a href={`/?${new URLSearchParams({ notebook: notebookId, cet6: "reading", reading: c.reading_id, reading_question: c.question_id || "" })}`}>回到原阅读</a>}
      {c.paper_id && <a href={`/?${new URLSearchParams({ notebook: notebookId, cet6: "papers", cet6_paper: c.paper_id, cet6_paper_question: String(c.paper_question || "") })}`}>回到原卷 · 第{c.paper_question}题</a>}
    </>}</article>)}
  </section>;
}
