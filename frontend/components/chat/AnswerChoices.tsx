/** @jsxImportSource react */
"use client";

import { useEffect, useState } from "react";
import MathText from "./MathText";

/** Only a contiguous, terminal A-D block is an answerable question. */
export function parseAnswerChoices(text: string): {label:string;text:string}[] {
  const outsideCode = text.replace(/```[\s\S]*?```/g, "");
  if (!/[?？]|单选|选择|哪[个项]|理解检查|小测|练习/.test(outsideCode)) return [];
  const lines = outsideCode.trim().split("\n");
  const groups: {choices:{label:string;text:string}[];end:number}[] = [];
  let current: {label:string;text:string}[] = [];
  let end = 0;
  for (const [index, line] of lines.entries()) {
    const match = line.match(/^\s*(?:[-*]\s*)?(?:\*\*)?([A-D])[.、．:：)）]\s*(?:\*\*)?(.+?)\s*$/);
    if (match) {
      if (match[1] === "A") { if(current.length)groups.push({choices:current,end});current=[]; }
      current.push({label:match[1],text:match[2].replace(/\*\*/g, "").trim()});
      end = index;
    } else if(line.trim() && current.length) {groups.push({choices:current,end});current=[];}
  }
  if(current.length)groups.push({choices:current,end});
  const group = groups.at(-1);
  const last = group?.choices;
  if(!last || last.length<2 || last.length>4 || last.some((x,i)=>x.label!==String.fromCharCode(65+i)))return [];
  const tail = lines.slice(group!.end + 1).join("\n").replace(/\*\*/g, "");
  if(tail.length > 180 || /(?:正确答案|答案是|答案[:：])\s*[:： ]*[A-D]/.test(tail))return [];
  return last;
}

export default function AnswerChoices({text,disabled,onChoose}:{text:string;disabled:boolean;onChoose:(prompt:string,display:string)=>void}) {
  const choices=parseAnswerChoices(text);
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => setSelected([]), [text]);
  const optionStart = text.search(/^\s*(?:[-*]\s*)?(?:\*\*)?A[.、．:：)）]/m);
  const multiple = optionStart >= 0 && /多选/.test(text.slice(0, optionStart).trim().split(/\n\s*\n/).at(-1) || "");
  if(!choices.length)return null;
  const submit = (labels: string[]) => {
    const display = choices.filter(c => labels.includes(c.label)).map(c => `${c.label}. ${c.text}`).join("；");
    onChoose(`针对刚才的题目（${text.slice(-4000)}），我选择 ${display}。请判断我的答案，解释原因，并根据我的理解程度继续引导。`, display);
  };
  return <div role="group" aria-label="点击选择答案" className="grid gap-2 sm:grid-cols-2">
    {multiple && <p className="text-sm sm:col-span-2">多选题：选完后提交。</p>}
    {choices.map(c=><button key={c.label} disabled={disabled} aria-pressed={multiple ? selected.includes(c.label) : undefined}
      className={`rounded-xl border border-emerald-200 px-4 py-3 text-left text-sm text-emerald-900 transition hover:bg-emerald-50 disabled:opacity-50 ${selected.includes(c.label) ? "bg-emerald-100" : "bg-white"}`}
      onClick={()=>multiple ? setSelected(current => current.includes(c.label) ? current.filter(label => label !== c.label) : [...current, c.label]) : submit([c.label])}>
      <MathText text={`${c.label}. ${c.text}`} /></button>)}
    {multiple && <button disabled={disabled || !selected.length} onClick={() => submit(selected)} className="rounded-xl bg-emerald-700 px-4 py-2 text-white disabled:opacity-50">提交所选答案</button>}
  </div>;
}
