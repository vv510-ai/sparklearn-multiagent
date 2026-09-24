/** @jsxImportSource react */
"use client";
import type { SourceEvidence as Evidence } from "@/lib/types";

export default function SourceEvidence({ evidence, citeBase }: { evidence?: Evidence[]; citeBase: string }) {
  if (!evidence?.length) return null;
  return <section className="chat-source-evidence" aria-label="引用原文">
    {evidence.map(item => <details key={item.index} id={`${citeBase}-source-${item.index}`} className="scroll-mt-4">
      <summary className="cursor-pointer text-xs font-semibold text-emerald-800">[{item.index}] {item.citation || item.source || "资料片段"}</summary>
      <p className="mt-2 text-xs text-slate-500">本次实际检索片段；有引用不代表每项结论都已核验。</p>
      {(item.chapter || item.page) && <p className="mt-2 text-xs text-slate-500">{item.chapter} {item.page ? `${item.location_kind || "页"} ${item.page}` : ""}</p>}
      <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-6 text-slate-700">{item.excerpt || item.preview || "这条历史记录未保存原文片段。"}</p>
      {!item.excerpt && item.preview && <p className="mt-2 text-xs text-amber-700">历史记录仅保存了预览，无法展示完整检索片段。</p>}
    </details>)}
  </section>;
}
