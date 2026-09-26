"use client";

export type DictionarySource = {
  status: "included" | "not_included"; headword: string; search_url?: string;
  provider?: string; notice?: string; version?: string; retrieved_at?: string;
  source_url?: string; extraction_url?: string; attribution?: string;
  license?: string; license_url?: string;
  senses?: { id: string; pos: string; definition: string; tags: string[] }[];
};
const labels: Record<string, string> = {
  verb: "动词", noun: "名词", adj: "形容词", adv: "副词",
  intransitive: "不及物", transitive: "及物", informal: "非正式",
  "not-comparable": "无比较级", ergative: "可及物或不及物", broadly: "广义",
};

export default function DictionaryEvidence({ word, evidence }: { word: string; evidence?: DictionarySource }) {
  if (evidence?.status !== "included") return <div className="mt-4 border-t border-slate-100 pt-3 text-xs leading-6 text-slate-600">
    <p>暂无内置词典摘录，AI 解释仍需核对。</p>
    <a className="inline-flex min-h-11 items-center text-emerald-800 underline underline-offset-4" target="_blank" rel="noopener noreferrer"
      href={evidence?.search_url || "https://en.wiktionary.org/w/index.php?title=Special:Search&search=" + encodeURIComponent(word)}>去词典查找（新窗口）</a>
  </div>;

  return <details className="mt-4 border-t border-slate-100 pt-2">
    <summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold text-emerald-800">查看词典原文</summary>
    <div className="space-y-3 pb-1 text-sm leading-6">
      <p className="text-xs text-slate-600">{evidence.notice}</p>
      <ol className="list-decimal space-y-3 pl-5">
        {evidence.senses?.map(sense => <li key={sense.id}>
          <span className="text-xs text-slate-500">{[sense.pos, ...sense.tags].map(tag => labels[tag] || tag).join(" · ")}</span>
          <p lang="en" className="break-words text-slate-700">{sense.definition}</p>
        </li>)}
      </ol>
      <div className="space-y-1 border-t border-slate-100 pt-3 text-xs text-slate-500">
        <p>{evidence.provider} · 摘录于 {evidence.retrieved_at?.slice(0, 10)}</p>
        <div className="flex flex-wrap gap-x-4">
          <a className="inline-flex min-h-11 items-center text-emerald-800 underline" href={evidence.source_url} target="_blank" rel="noopener noreferrer">完整词条（新窗口）</a>
          <a className="inline-flex min-h-11 items-center text-emerald-800 underline" href={evidence.extraction_url} target="_blank" rel="noopener noreferrer">提取来源（新窗口）</a>
          <a className="inline-flex min-h-11 items-center text-emerald-800 underline" href={evidence.license_url} target="_blank" rel="noopener noreferrer">{evidence.license}</a>
        </div>
        <p>{evidence.attribution}</p>
      </div>
    </div>
  </details>;
}
