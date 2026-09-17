import type { Textbook } from "@/lib/assessment";

export default function TextbookScope({ book }: { book: Textbook }) {
  return <section className="textbook-scope" aria-label="教材依据与范围">
    <strong>{book.title} · {book.version}</strong>
    <p>{book.scope_note}</p>
    <details><summary>查看已接入的章节与原文</summary>
      <ul>{book.sections.map(s => <li key={s.id}><a href={s.url} target="_blank" rel="noopener noreferrer">{s.title} ↗</a></li>)}</ul>
      <small>教材原文用于核对知识；讲解、起点题与新题由本站另行编写。<a href={book.license_url} target="_blank" rel="noopener noreferrer">来源与许可</a></small>
    </details>
  </section>;
}
