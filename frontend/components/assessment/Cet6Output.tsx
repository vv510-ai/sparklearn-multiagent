"use client";

import { useEffect, useState } from "react";

const PROMPTS: Record<string, string> = {
  cet6_writing: "写 120–150 词，讨论大学是否应该提供安静的协作学习空间。给出观点、理由和具体例子，并考虑一个限制。这是本站分步练习长度。",
  cet6_translation: "请译成英文：近年来，越来越多的大学向公众开放图书馆。读者不仅可以借阅图书，还可以参加文化活动。这些服务有助于促进终身学习。",
};

export default function Cet6Output({ assessmentId, kp, onLearn }: { assessmentId: string; kp: string; onLearn: (prompt: string) => void }) {
  const key = `cet6-output:${assessmentId}:${kp}`;
  const [draft, setDraft] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => { try { const value = localStorage.getItem(key) || ""; setDraft(value); setSaved(Boolean(value)); } catch { /* Memory state remains usable. */ } }, [key]);
  const change = (value: string) => {
    setDraft(value);
    try { localStorage.setItem(key, value); setSaved(true); } catch { setSaved(false); }
  };
  return <section className="cet6-output" aria-label="六级实际输出训练">
    <h3>{kp === "cet6_writing" ? "自己写一段，再请小知反馈" : "先独立翻译，再核对信息"}</h3>
    <p>{PROMPTS[kp]}可以分次完成，先写出当前能表达的部分。</p>
    <label htmlFor="cet6-draft">你的英文原稿</label>
    <textarea id="cet6-draft" lang="en" maxLength={6000} rows={7} value={draft} onChange={e => change(e.target.value)} placeholder="先独立尝试，暂时不会的部分也可以保留…" />
    <p className="entry-note">{saved ? "草稿已保存在此浏览器。" : "草稿在当前页面保留。"}提交后会进入当前课程的对话。反馈用于修订，不换算官方分数，也不计入独立测评正确率。</p>
    <button className="intake-primary" disabled={!draft.trim()} onClick={() => onLearn(`请作为我的大学英语六级学习助教，反馈下面的${kp === "cet6_writing" ? "写作" : "翻译"}原稿。请先指出做对的地方，再按内容完整性、逻辑组织、语言准确性给出具体原句、问题和可选修改；保留合理的不同表达，不编造官方分数，不把反馈视为已掌握的证据。最后只让我自己改写一个关键片段，等待我作答。\n\n题目：${PROMPTS[kp]}\n\n我的原稿：\n${draft}`)}>提交给小知，逐句反馈</button>
  </section>;
}
