"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Check, RotateCcw } from "lucide-react";
import { BRAND } from "@/lib/brand";

const steps = ["先独立作答", "定位知识缺口", "换题复测", "查看下一步依据"];
const questions = [
  { stem: "根结点为 A，左孩子为 B，右孩子为 C。中序遍历的顺序是？", choices: ["A → B → C", "B → A → C", "B → C → A"], answer: 1 },
  { stem: "换一棵树：根为 M，左孩子为 K，右孩子为 P。中序遍历的顺序是？", choices: ["K → P → M", "M → K → P", "K → M → P"], answer: 2 },
];

export default function ReviewPage() {
  const [step, setStep] = useState(0);
  const [choices, setChoices] = useState<number[]>([-1, -1]);
  const [hinted, setHinted] = useState(false);
  const [retestHint, setRetestHint] = useState(false);
  const questionIndex = step === 2 ? 1 : 0;
  const question = questions[questionIndex];
  const initialCorrect = choices[0] === questions[0].answer;
  const retestCorrect = choices[1] === questions[1].answer;
  function reset() { setStep(0); setChoices([-1, -1]); setHinted(false); setRetestHint(false); }
  return <main className="min-h-dvh bg-[#F5F5EE] px-5 py-7 text-[#193A31]">
    <div className="mx-auto max-w-4xl">
      <nav className="flex flex-wrap items-center justify-between gap-3 text-sm"><Link href="/" className="text-lg font-bold">{BRAND.name} <span className="text-xs font-normal">LearnLoop</span></Link><div className="flex gap-5"><Link href="/evidence">项目证据</Link><Link href="/teacher">教师试点</Link></div></nav>
      <div className="mt-14 max-w-2xl"><span className="rounded-full border border-emerald-900/20 px-3 py-1 text-xs">三分钟 · 交互演示</span><h1 className="mt-5 text-3xl font-semibold leading-tight sm:text-5xl">答案之后，<br/>才是学习的下一步。</h1><p className="mt-5 text-sm leading-7 text-[#62766E]">亲手完成两次作答，看看独立完成与提示后完成，会怎样改变学习建议。此页是固定示例，记录只保留在当前页面，不计入个人画像或教学效果统计。</p></div>
      <ol className="my-9 grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="体验进度">{steps.map((label, i) => <li key={label} aria-current={step === i ? "step" : undefined} className={`rounded-2xl border p-4 text-xs ${i === step ? "border-[#173F34] bg-[#173F34] text-white" : "border-[#DEE4DC] bg-white/60"}`}><span className="mb-2 block text-lg">{i < step ? <Check size={20}/> : `0${i+1}`}</span>{label}</li>)}</ol>
      <section className="rounded-[28px] border border-[#DEE4DC] bg-white p-6 shadow-sm sm:p-10" aria-live="polite">
        {(step === 0 || step === 2) && <>
          <p className="text-xs font-semibold text-[#728178]">数据结构 · 二叉树 · {step === 0 ? "初次诊断" : "独立复测"}</p><h2 className="mt-4 text-xl font-semibold leading-9">{question.stem}</h2>
          <div className="my-6 grid gap-3">{question.choices.map((label, i) => <label key={label} className={`flex cursor-pointer gap-3 rounded-xl border p-4 text-sm ${choices[questionIndex] === i ? "border-emerald-700 bg-emerald-50" : "border-slate-200"}`}><input type="radio" name={`q${questionIndex}`} checked={choices[questionIndex] === i} onChange={() => setChoices(choices.map((v, n) => n === questionIndex ? i : v))}/>{label}</label>)}</div>
          {(step === 0 ? hinted : retestHint) ? <p className="mb-5 rounded-xl bg-amber-50 p-4 text-sm leading-7">提示：中序先访问左子树，然后根结点，最后右子树。本次会记录为“使用了提示”。</p> : <button onClick={() => step === 0 ? setHinted(true) : setRetestHint(true)} className="mb-5 block text-sm text-[#6F796F] underline underline-offset-4">我需要一个提示</button>}
          <button onClick={() => setStep(step+1)} disabled={choices[questionIndex] < 0} className="inline-flex items-center gap-2 rounded-full bg-[#173F34] px-6 py-3 text-sm text-white disabled:opacity-40">提交本次作答 <ArrowRight size={16}/></button>
        </>}
        {step === 1 && <>
          <p className="text-xs text-[#728178]">诊断依据 · 来自刚才的作答</p><h2 className="mt-4 text-2xl font-semibold">{initialCorrect ? hinted ? "答对了，再试一次独立完成。" : "顺序正确，接着检验能否迁移。" : "需要区分：根结点何时访问。"}</h2>
          <p className="mt-5 text-sm leading-8">你选择了 {questions[0].choices[choices[0]]}，{hinted ? "使用过提示" : "未使用提示"}。{initialCorrect ? "一次正确作答还不足以说明稳定掌握。" : "中序遍历的根结点在中间访问；前序才是根先，后序是根后。"}</p>
          <div className="my-6 rounded-2xl bg-[#F1F6F0] p-6"><div className="text-xs text-[#728178]">复习规则</div><div className="mt-3 text-2xl font-semibold">左子树 → 根结点 → 右子树</div><p className="mt-3 text-sm leading-7">回到原题，左孩子 B 先访问，再访问根 A，最后是右孩子 C。因此为 B → A → C。</p></div>
          <button onClick={() => setStep(2)} className="inline-flex items-center gap-2 rounded-full bg-[#173F34] px-6 py-3 text-sm text-white">用新题独立复测 <ArrowRight size={16}/></button>
        </>}
        {step === 3 && <>
          <p className="text-xs text-[#728178]">本页作答记录 · 固定示例规则</p><h2 className="mt-4 text-2xl font-semibold">{retestCorrect && !retestHint ? "下一步：练习多层二叉树。" : "下一步：再练一次访问顺序。"}</h2>
          <div className="my-6 grid gap-3 sm:grid-cols-2">{[0,1].map(i => <div key={i} className="rounded-2xl border border-slate-200 p-5"><p className="text-xs text-slate-500">{i === 0 ? "初次诊断" : "换题复测"}</p><p className="mt-2 font-semibold">{choices[i] === questions[i].answer ? "正确" : "错误"} · {(i === 0 ? hinted : retestHint) ? "使用提示" : "独立完成"}</p><p className="mt-2 text-xs text-slate-500">实际选择：{questions[i].choices[choices[i]]}</p></div>)}</div>
          <p className="text-sm leading-8">{retestCorrect && !retestHint ? "新题独立答对支持进入更复杂练习；仍需隔日或隔周复习检验保持。" : retestCorrect ? "提示后答对说明规则可以理解；下一次需要不看提示，才能增加独立掌握的证据。" : "复测尚未答对，继续巩固先序、中序、后序的差别，并用新题复查。"} 当前没有延迟复习记录，因此不会显示保持率。</p>
          <p className="mt-4 text-xs leading-6 text-slate-500">正式学习工作台会保存作答、提示使用和引用记录，并更新知识追踪估计。此体验不调用付费模型，也不宣称测量了学习效果。</p>
          <div className="mt-7 flex flex-wrap gap-3"><Link href="/" className="inline-flex items-center gap-2 rounded-full bg-[#173F34] px-6 py-3 text-sm text-white">开始我的课程学习 <ArrowRight size={16}/></Link><button onClick={reset} className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-5 py-3 text-sm"><RotateCcw size={15}/>重新体验</button></div>
        </>}
      </section>
      <p className="my-8 text-xs text-[#7B877D]">学习路径可以提出建议；真实教学效果需要预先确定实验方案、收集原始记录并独立复核。</p>
    </div>
  </main>;
}
