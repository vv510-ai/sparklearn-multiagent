"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { readingDate, type ReadingLibrary } from "@/lib/reading";

export default function ReadingProgress({ notebookId, onOpen }: { notebookId: string; onOpen: (id: string) => void }) {
  const [data, setData] = useState<ReadingLibrary | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    void apiGet<ReadingLibrary>(`/notebooks/${notebookId}/reading`).then(result => { if (active) setData(result); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [notebookId]);
  return <section className="reading-hub reading-today" aria-label="阅读学习记录">
    <h2>阅读学习记录</h2>
    {!data ? <p>{error ? "阅读记录暂时无法加载，请重新进入学习情况。" : "正在读取本课阅读记录…"}</p> : <>
      <p>已完成自备材料 {data.private_completed} 篇 · 体验示例 {data.demo_completed} 篇 · 到期阅读 {data.due} 项</p>
      <p className="reading-muted">首次作答、即时订正与隔时复习分别记录，不计入测评掌握度，也不换算六级分数。自备材料的来源和答案尚未经本站核验。</p>
      {data.items.length ? data.items.map(item => <button className="reading-list-item" key={item.id} onClick={() => onOpen(item.id)}><span><strong>{item.title}</strong><small>{item.demo ? "体验示例（非真题）" : "自备材料"} · {item.first ? `首次 ${item.first.correct}/${item.first.total} · ${item.first.used_help ? "使用过帮助" : "自述独立"}` : "尚未提交"}</small><small>到期独立复习 {item.reviews} 次 · 下次：{readingDate(item.due_at)}</small></span><span>查看 →</span></button>) : <p className="reading-muted">完成第一篇阅读后，这里会保留你的首次答案与复习记录。</p>}
    </>}
  </section>;
}
