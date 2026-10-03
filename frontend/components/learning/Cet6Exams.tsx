"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Headphones, PenLine, Type, ArrowLeft, ArrowRight, Check } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { cet6Route } from "@/lib/cet6";
import { readingError, readingRequestId } from "@/lib/reading";
import { draftEquals, examLabels, type ExamDraft, type ExamKind, type ExamQuestion, type ExamRequest, type ExamSession, type ExamSummary } from "@/lib/cet6-exams";
import SourcePaperReader from "./SourcePaperReader";
import "./cet6-exams.css";

const kinds: ExamKind[] = ["listening", "reading", "writing", "translation"];
const hints = { listening: "原始录音 · 25 题", reading: "三种题型 · 30 题", writing: "保留原稿 · 具体修改建议", translation: "信息与表达 · 逐处反馈" };
function initialSelection() {
  const params = new URLSearchParams(window.location.search);
  const kind = params.get("exam_kind") as ExamKind;
  return { kind: kinds.includes(kind) ? kind : null, paper: params.get("exam_paper") || "" };
}
function route(notebook: string, kind: ExamKind | null, paper = "") {
  cet6Route(notebook,"exams");
  const url = new URL(window.location.href);
  if (kind) url.searchParams.set("exam_kind",kind); else url.searchParams.delete("exam_kind");
  if (paper) url.searchParams.set("exam_paper",paper); else url.searchParams.delete("exam_paper");
  window.history.replaceState(null,"",url.pathname+url.search);
}

export default function Cet6Exams({ notebookId, userId, initialKind, onFocus }: { notebookId: string; userId: string; initialKind?: ExamKind; onFocus: (active: boolean) => void }) {
  const first = useRef(typeof window === "undefined" ? { kind:null, paper:"" } : initialSelection());
  const [kind,setKind] = useState<ExamKind | null>(initialKind || first.current.kind), [paper,setPaper]=useState(first.current.paper);
  const [items,setItems]=useState<ExamSummary[]>([]),[year,setYear]=useState(2026),[error,setError]=useState(""),[retry,setRetry]=useState(0),[loaded,setLoaded]=useState(false);
  useEffect(()=>{onFocus(!!paper);return()=>onFocus(false);},[paper,onFocus]);
  useEffect(() => { let alive=true; setLoaded(false); void apiGet<{items:ExamSummary[]}>(`/notebooks/${notebookId}/cet6/exams`).then(r=>{if(alive){setItems(r.items);setLoaded(true);setError("");}}).catch(e=>{if(alive)setError(readingError(e));}); return()=>{alive=false;}; },[notebookId,retry,paper]);
  const selectKind=(next:ExamKind|null)=>{setKind(next);setPaper("");route(notebookId,next);};
  if(kind && paper) return <ExamAttempt key={`${userId}:${notebookId}:${paper}:${kind}`} notebookId={notebookId} userId={userId} paperId={paper} kind={kind} onExit={()=>{setPaper("");route(notebookId,kind);}} />;
  return <section className="cet6-exams" aria-label="六级真题练习">
    <div className="exam-picker-heading"><span className="exam-eyebrow">真题练习</span><h2>{kind?`选择${examLabels[kind]}真题` : "今天练哪个板块？"}</h2><p>选板块，选套卷，完成后查看结果与解析。</p></div>
    <div className="exam-kind-grid">{kinds.map((k,i)=>{const Icon=[Headphones,BookOpen,PenLine,Type][i];return <button key={k} aria-pressed={kind===k} onClick={()=>selectKind(k)}><Icon size={24}/><strong>{examLabels[k]}</strong><span>{hints[k]}</span><ArrowRight size={18}/></button>;})}</div>
    {error&&<div role="alert" className="exam-error">{error}<button onClick={()=>setRetry(n=>n+1)}>重试真题列表</button></div>}
    {kind&&<><div className="exam-catalogue-bar"><h3>按考试时间选择</h3><label>年份<select aria-label="真题年份" value={year} onChange={e=>setYear(Number(e.target.value))}>{[2026,2025,2024].map(y=><option key={y}>{y}</option>)}</select></label></div>
      {!loaded&&!error&&<p role="status">正在读取套卷…</p>}
      <div className="exam-paper-list">{items.filter(p=>p.year===year).map(p=><article className="exam-paper-card" key={p.id}><div><span className="exam-eyebrow">{p.ready?"可在本站答题":"原站资料"}</span><h3>{p.title}</h3><p>{p.ready?`${examLabels[kind]} · ${p.counts?.[kind]} ${["reading","listening"].includes(kind)?"题":"篇"} · ${p.progress?.[kind]?.phase==="feedback"?"已提交，可查看解析":p.progress?.[kind]?"有作答记录，可继续":"尚未开始"}`:"这套尚未完成本站逐题接入，可先查看来源材料。"}</p></div>{p.ready?<button className="primary-action" onClick={()=>{setPaper(p.id);route(notebookId,kind,p.id);}}>{p.progress?.[kind]?.phase==="feedback"?"查看结果":p.progress?.[kind]?"继续作答":"开始作答"}<ArrowRight size={17}/></button>:<a className="secondary-action" href={p.source_url} target="_blank" rel="noreferrer">查看原站资料 ↗</a>}</article>)}</div>
      <p className="exam-muted">目前已接入 2026 年 6 月第 1 套完整四个板块。2026 年 12 月尚未开考；其他套卷通过核对后再开放本站答题。</p></>}
  </section>;
}

type LocalCopy = ExamDraft & { version: string; base_revision: number; pending: ExamRequest | null };
function sourceQuestion(source: string, q: ExamQuestion, kind: ExamKind): {stem:string; options:Record<string,string>} {
  if(q.number<36 && kind==="reading") {
    const bank=source.match(/A\)\s*anywhere[\s\S]*?(?=Section B)/)?.[0] || "";
    const entries=[...bank.matchAll(/([A-O])\)\s*([A-Za-z]+)/g)].map(m=>[m[1],m[2]]);
    return {stem:`选词填空 · 第 ${q.number} 空`,options:Object.fromEntries(entries)};
  }
  const start=new RegExp(`(?:^|\\n)(?:\\d{1,2}\\.\\s*)?${q.number}\\.\\s*`).exec(source);
  if(!start) return {stem:`第 ${q.number} 题 · 请对照原卷`,options:{}};
  const tail=source.slice(start.index+start[0].length);
  const end=new RegExp(`(?:^|\\n)(?:\\d{1,2}\\.\\s*)?${q.number+1}\\.\\s*|(?:^|\\n)Part [IVX]+|(?:^|\\n)Section [ABC]|(?:^|\\n)Questions \\d`).exec(tail);
  const part=(end?tail.slice(0,end.index):tail).trim();
  if(q.number>=36&&q.number<=45&&kind==="reading") return {stem:part.replace(/\s+/g," "),options:{}};
  const matches=[...part.matchAll(/(?:^|\s)([A-D])\)\s*/g)],options:Record<string,string>={};
  for(let i=0;i<matches.length;i++){const m=matches[i];options[m[1]]=part.slice(m.index!+m[0].length,matches[i+1]?.index??part.length).replace(/\s+/g," ").trim();}
  return {stem:matches.length?part.slice(0,matches[0].index).replace(/\s+/g," ").trim()||`第 ${q.number} 题（问题在录音中）`:`第 ${q.number} 题 · 请对照原卷`,options};
}

function ExamAttempt({notebookId,userId,paperId,kind,onExit}:{notebookId:string;userId:string;paperId:string;kind:ExamKind;onExit:()=>void}) {
  const base=`/notebooks/${notebookId}/cet6/exams/${paperId}/${kind}`, key=`learnloop:exam:${userId}:${notebookId}:${paperId}:${kind}`;
  const [state,setState]=useState<ExamSession|null>(null),[draft,setDraft]=useState<ExamDraft>({answers:{},text:""});
  const [error,setError]=useState(""),[notice,setNotice]=useState(""),[busy,setBusy]=useState(false),[dirty,setDirty]=useState(false),[retry,setRetry]=useState(0);
  const [index,setIndex]=useState(0),[sourcePage,setSourcePage]=useState(kind==="reading"?6:kind==="translation"?14:1),[mobilePane,setMobilePane]=useState<"source"|"answer">("source");
  const [sourceText,setSourceText]=useState(""),[showMissed,setShowMissed]=useState(false),[onlyWrong,setOnlyWrong]=useState(false),[conflict,setConflict]=useState(false),[reviewBusy,setReviewBusy]=useState(false),[audioError,setAudioError]=useState(false);
  const active=useRef(true),stateRef=useRef<ExamSession|null>(null),draftRef=useRef<ExamDraft>(draft),busyRef=useRef(false),pending=useRef<ExamRequest|null>(null),errorRef=useRef(false),reviewStarted=useRef("");
  const saveRef=useRef<(action:ExamRequest["action"],allow?:boolean)=>Promise<void>>(async()=>{}),heading=useRef<HTMLHeadingElement>(null);
  const feedback=state?.phase==="feedback",questions=state?.material.questions||[],objective=kind==="reading"||kind==="listening";
  const persist=useCallback(()=>{const saved=stateRef.current;if(!saved)return;try{localStorage.setItem(key,JSON.stringify({...draftRef.current,version:saved.version,base_revision:saved.revision,pending:pending.current}));}catch{if(active.current)setNotice("浏览器暂不能保留离线副本，请等待保存到账号后再离开。");}},[key]);
  const accept=useCallback((next:ExamSession)=>{stateRef.current=next;setState(next);},[]);
  const load=useCallback(async()=>{
    try{
      const next=await apiGet<ExamSession>(base);if(!active.current)return;
      let local:LocalCopy|null=null;try{local=JSON.parse(localStorage.getItem(key)||"null");}catch{/* malformed local copy */}
      accept(next);let restored:ExamDraft={answers:next.answers,text:next.text};
      if(next.phase==="answer"&&local?.version===next.version){
        restored={answers:local.answers,text:local.text};pending.current=local.pending;
        const acknowledged=local.pending&&next.revision===local.pending.revision+1&&draftEquals(next,local.pending);
        if(acknowledged)pending.current=null;
        if(local.base_revision!==next.revision&&!acknowledged){setConflict(true);setError("另一页面保存了不同版本。你的本地输入已保留，请比较后选择。");}
        else{setConflict(false);setError("");}
      }else{pending.current=null;setConflict(false);setError("");if(next.phase==="feedback")localStorage.removeItem(key);}
      draftRef.current=restored;setDraft(restored);setDirty(!draftEquals(restored,next));
      errorRef.current=false;setNotice("已读取账号记录");
      if(local?.pending?.action==="submit"&&next.phase==="feedback"&&next.first?.submission_id===local.pending.request_id)setNotice("上次提交已成功，结果已恢复。");
    }catch(e){if(active.current)setError(readingError(e));}
  },[base,key,accept]);
  useEffect(()=>{active.current=true;void load();return()=>{active.current=false;};},[load,retry]);
  const edit=(patch:Partial<ExamDraft>)=>{if(feedback||conflict||pending.current?.action==="submit")return;const next={...draftRef.current,...patch};draftRef.current=next;setDraft(next);setDirty(true);setShowMissed(false);persist();};
  const save=useCallback(async(action:ExamRequest["action"],allow=false)=>{
    const current=stateRef.current;if(!current||busyRef.current||conflict)return;
    // Resolve an uncertain request using exactly the same id/body before any later action.
    if(pending.current&&pending.current.action!==action){await saveRef.current(pending.current.action);if(pending.current||errorRef.current)return;await saveRef.current(action,allow);return;}
    const snapshot={answers:{...draftRef.current.answers},text:draftRef.current.text};
    const request=pending.current||{...snapshot,request_id:readingRequestId(),revision:current.revision,version:current.version,action,allow_incomplete:allow};
    pending.current=request;persist();busyRef.current=true;setBusy(true);setError("");errorRef.current=false;
    try{
      const result=await apiPost<ExamSession>(base,request);if(!active.current)return;
      accept(result);pending.current=null;
      if(action!=="save"){draftRef.current={answers:result.answers,text:result.text};setDraft(draftRef.current);setDirty(false);setShowMissed(false);setIndex(0);setMobilePane("answer");try{localStorage.removeItem(key);}catch{}requestAnimationFrame(()=>heading.current?.focus());}
      else{const changed=!draftEquals(draftRef.current,result);setDirty(changed);persist();if(changed)setTimeout(()=>void saveRef.current("save"),650);}
      setNotice(action==="submit"?"提交成功，首次作答已保存。":action==="restart"?"已开启新一轮，上一轮记录已保留。":"已保存到账号");
    }catch(e){if(!active.current)return;const message=readingError(e),raw=e instanceof Error?e.message:"";setError(message);errorRef.current=true;
      if(raw.includes("→ 409")){pending.current=null;setConflict(true);}
      else if(raw.includes("→ 422")){pending.current=null;}
      persist();
    }finally{busyRef.current=false;if(active.current)setBusy(false);}
  },[base,key,accept,conflict,persist]);
  saveRef.current=save;
  useEffect(()=>{if(!state||feedback||conflict||!dirty)return;const timer=setTimeout(()=>{if(!errorRef.current)void saveRef.current("save");},800);return()=>clearTimeout(timer);},[draft,state?.phase,conflict,dirty,feedback]);
  useEffect(()=>{const online=()=>{errorRef.current=false;if(pending.current||!draftEquals(draftRef.current,stateRef.current||{answers:{},text:""}))void saveRef.current(pending.current?.action||"save");};window.addEventListener("online",online);return()=>window.removeEventListener("online",online);},[]);
  useEffect(()=>{const warn=(e:BeforeUnloadEvent)=>{if(dirty){persist();e.preventDefault();e.returnValue="";}};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn);},[dirty,persist]);
  const review=useCallback(async()=>{
    if(reviewBusy)return;setReviewBusy(true);setError("");
    try{const result=await apiPost<ExamSession>(base+"/review",{});if(active.current)accept(result);}catch{if(active.current)setNotice("反馈仍可能在生成，原稿已保存；正在核对账号结果。");}finally{if(active.current)setReviewBusy(false);}
  },[base,accept,reviewBusy]);
  useEffect(()=>{const id=state?.first?.submission_id;if(state?.review?.status==="pending"&&id&&reviewStarted.current!==id){reviewStarted.current=id;void review();}},[state?.review?.status,state?.first?.submission_id,review]);
  useEffect(()=>{if(!feedback||objective||state?.review?.status==="ready"||state?.review?.status==="unavailable"||state?.review?.status==="failed")return;const timer=setInterval(()=>{void apiGet<ExamSession>(base).then(r=>{if(active.current)accept(r);}).catch(()=>{});},3000);return()=>clearInterval(timer);},[feedback,objective,state?.review?.status,base,accept]);
  const sourceCallback=useCallback((value:string)=>setSourceText(value),[]);
  if(!state)return <section className="cet6-exams"><button onClick={onExit}><ArrowLeft size={16}/>返回套卷</button>{error?<div className="exam-error" role="alert">{error}<button onClick={()=>setRetry(n=>n+1)}>重试读取作答</button></div>:<p role="status">正在准备本板块…</p>}</section>;
  const material=state.material,missing=questions.filter(q=>!draft.answers[String(q.number)]),q=questions[Math.min(index,Math.max(0,questions.length-1))];
  const copy=q?sourceQuestion(sourceText,q,kind):null;
  const move=(next:number)=>{setIndex(next);setSourcePage(questions[next].page);setMobilePane("answer");};
  const submit=()=>{if(objective&&missing.length){setShowMissed(true);setMobilePane("answer");requestAnimationFrame(()=>document.getElementById("exam-missing")?.focus());}else void save("submit");};
  const select=(letter:string)=>{if(!q)return;edit({answers:{...draftRef.current.answers,[q.number]:letter}});};
  const feedbackQuestions=onlyWrong?questions.filter(item=>state.first?.answers[String(item.number)]!==item.answer):questions;
  return <section className="cet6-exams" aria-label={`${examLabels[kind]}真题作答`}>
    <div className="exam-attempt-top"><button className="exam-back" onClick={onExit}><ArrowLeft size={16}/>返回套卷</button><span className="exam-muted">{material.minutes} 分钟参考用时</span></div>
    <h1 ref={heading} tabIndex={-1}>{material.paper_title} · {examLabels[kind]}</h1><p className="exam-muted">原站试卷联动答题 · 答案对应当前原卷的选项顺序</p>
    {objective&&feedback&&<div className="exam-result-summary"><Check size={25}/><div><strong>答对 {state.first?.correct} / {state.first?.total} 题</strong><p>已答 {state.first?.answered} 题 · 未答 {(state.first?.total||0)-(state.first?.answered||0)} 题 · 这是本板块练习结果，不换算六级成绩。</p></div></div>}
    {material.audio_url&&<div className="exam-audio"><label htmlFor="exam-original-audio">本套原站听力录音</label><audio id="exam-original-audio" aria-label="本套原站听力录音" controls preload="metadata" src={material.audio_url} onError={()=>setAudioError(true)}/><p className="exam-muted">{material.audio_note}</p>{audioError&&<p role="alert">原站录音暂不可用。你的作答仍会保存。<a href={material.audio_url} target="_blank" rel="noreferrer">在原站打开录音 ↗</a></p>}</div>}
    <div className="exam-mobile-tabs" role="group" aria-label="原卷与作答切换"><button aria-pressed={mobilePane==="source"} onClick={()=>setMobilePane("source")}>阅读原卷</button><button aria-pressed={mobilePane==="answer"} onClick={()=>setMobilePane("answer")}>{feedback?"结果与解析":"我的作答"}{objective?` · ${Object.keys(draft.answers).length}/${questions.length}`:""}</button></div>
    <div className="exam-workspace">
      <div className="exam-source-pane" data-mobile-visible={mobilePane==="source"}><SourcePaperReader url={material.pdf_url} sourceUrl={material.source_url} pages={material.pages} page={sourcePage} onPage={setSourcePage} expectedHash={material.pdf_sha256} feedback={!!feedback} onSourceText={sourceCallback} kind={kind}/></div>
      <div className="exam-answer-pane" data-mobile-visible={mobilePane==="answer"}>
        <div className="exam-save-state" role="status">{busy?"正在保存…":dirty?"有新输入；离线副本保留在本账号的浏览器中":notice}</div>
        {error&&<div className="exam-error" role="alert"><p>{error}</p>{!conflict&&<button disabled={busy} onClick={()=>{errorRef.current=false;void save(pending.current?.action||"save");}}>重试保存／提交</button>}</div>}
        {conflict&&<div className="exam-conflict"><h3>核对另一页面的记录</h3><p>账号版本：已答 {Object.keys(state.answers).length} 题{state.text?`；原稿：${state.text.slice(0,200)}`:""}。</p><p>本页版本：已答 {Object.keys(draft.answers).length} 题{draft.text?`；原稿：${draft.text.slice(0,200)}`:""}。</p><button onClick={async()=>{const latest=await apiGet<ExamSession>(base);if(!active.current)return;accept(latest);draftRef.current={answers:latest.answers,text:latest.text};setDraft(draftRef.current);pending.current=null;setConflict(false);setDirty(false);setError("");persist();}}>使用账号版本</button><button onClick={async()=>{try{const latest=await apiGet<ExamSession>(base);if(!active.current)return;accept(latest);if(latest.phase!=="answer"){setError("另一页面已提交，本页草稿仍保留。请使用账号版本查看结果。");return;}pending.current=null;setConflict(false);setDirty(true);setError("");errorRef.current=false;persist();}catch(e){setError(readingError(e));}}}>保留本页输入，准备保存</button></div>}
        {showMissed&&<div id="exam-missing" tabIndex={-1} className="exam-missing" role="alert"><h3>还有 {missing.length} 题未作答</h3><p>点击题号返回检查，也可以保留空题提交。</p><div className="exam-number-grid">{missing.map(item=><button key={item.number} onClick={()=>{move(questions.indexOf(item));setShowMissed(false);}}>{item.number}</button>)}</div><div className="exam-actions"><button onClick={()=>{move(questions.indexOf(missing[0]));setShowMissed(false);}}>返回第一道漏题</button><button disabled={busy||!Object.keys(draft.answers).length} onClick={()=>void save("submit",true)}>仍然提交本板块</button></div></div>}
        {objective&&!feedback&&q&&<><nav className="exam-number-grid" aria-label="本板块题号">{questions.map((item,i)=><button key={item.number} aria-label={`第 ${item.number} 题${draft.answers[String(item.number)]?"，已答":"，未答"}`} aria-current={i===index?"step":undefined} data-answered={!!draft.answers[String(item.number)]} onClick={()=>move(i)}>{item.number}{draft.answers[String(item.number)]&&<span aria-hidden="true">✓</span>}</button>)}</nav>
          <fieldset className="exam-question" disabled={conflict||pending.current?.action==="submit"}><legend>第 {q.number} 题 · {q.group}</legend><p lang={kind==="reading"&&q.number<36?"zh-CN":"en"} className="exam-question-stem">{copy?.stem}</p><button className="exam-context-link" type="button" onClick={()=>{setSourcePage(q.page);setMobilePane("source");}}>查看原卷第 {q.page} 页</button><div className={`exam-choice-list ${q.choices.length>4?"exam-many-choices":""}`}>{q.choices.map(letter=><label key={letter} data-selected={draft.answers[String(q.number)]===letter}><input type="radio" name={`exam-${q.number}`} value={letter} checked={draft.answers[String(q.number)]===letter} onChange={()=>select(letter)}/><span><b>{letter}</b>{copy?.options[letter]&&<span lang="en">{copy.options[letter]}</span>}</span></label>)}</div></fieldset>
          <div className="exam-actions"><button disabled={index===0} onClick={()=>move(index-1)}>上一题</button>{index<questions.length-1?<button className="primary-action" onClick={()=>move(index+1)}>下一题<ArrowRight size={17}/></button>:<span>已到本板块最后一题</span>}<button disabled={!draft.answers[String(q.number)]||busy} onClick={()=>{const answers={...draft.answers};delete answers[String(q.number)];edit({answers});}}>清除本题选择</button></div>
        </>}
        {!objective&&<><label className="exam-essay-label" htmlFor="exam-essay">{feedback?"首次提交的原稿":"我的作答"}</label><textarea id="exam-essay" className="exam-essay" lang="en" rows={15} maxLength={10000} value={draft.text} readOnly={!!feedback} disabled={conflict||pending.current?.action==="submit"} onChange={e=>edit({text:e.target.value})} placeholder={kind==="writing"?"请先阅读原卷写作要求，再在这里完成作文。":"请先阅读原卷中文段落，再在这里完成英译。"}/><p className="exam-muted">当前 {draft.text.trim()?draft.text.trim().split(/\s+/).length:0} 个空格分隔词{kind==="writing"?" · 原题要求 150—200 词":""}。{feedback?"原稿保留，可对照下方建议修改理解。":"输入自动保存。"}</p></>}
        {!feedback&&<div className="exam-submit-bar"><span>{objective?`已答 ${Object.keys(draft.answers).length} / ${questions.length} 题`:"提交后查看针对原稿的反馈"}</span><button className="primary-action" disabled={busy||conflict} onClick={submit}>{busy?"正在保存…":"提交本板块"}</button></div>}
        {objective&&feedback&&<><div className="exam-feedback-heading"><h3>逐题解析</h3><label><input type="checkbox" checked={onlyWrong} onChange={e=>setOnlyWrong(e.target.checked)}/>只看错题与未答题</label></div><p className="exam-muted">以下解释选项与依据的关系，不能仅凭一个错误选项确定个人错因。</p>{!feedbackQuestions.length&&<p>本轮全部答对。仍可查看依据，检查是否凭猜测答对。</p>}{feedbackQuestions.map(item=>{const chosen=state.first?.answers[String(item.number)],correct=chosen===item.answer;return <details className="exam-analysis" key={item.number} open={!correct}><summary><span>第 {item.number} 题</span><strong>{correct?"✓ 正确":chosen?"× 需订正":"— 未作答"}</strong><span>你的答案 {chosen||"未答"} · 参考答案 {item.answer}</span></summary><p><b>依据位置：</b>{item.location}</p><p>{item.explanation}</p>{chosen&&<div className="exam-selected-reason"><b>你选择 {chosen}：</b>{item.option_reasons?.[chosen]}</div>}<p><b>这次怎么订正：</b>{item.tip}</p><button className="exam-context-link" onClick={()=>{setSourcePage(item.evidence_page||item.page);setMobilePane("source");}}>回到原卷第 {item.evidence_page||item.page} 页核对</button><details><summary>查看其他选项的区别</summary>{Object.entries(item.option_reasons||{}).filter(([letter])=>letter!==chosen).map(([letter,reason])=><p key={letter}><b>{letter}：</b>{reason}</p>)}</details></details>;})}</>}
        {!objective&&feedback&&<section className="exam-model-feedback" aria-label="原稿分析"><h3>原稿分析</h3>{state.review?.status==="ready"&&state.review.content?<><p className="exam-muted">{state.review.model} · {state.review.note}</p><p>{state.review.content.summary}</p>{!!state.review.content.strengths.length&&<><h4>可以保留的表达</h4><ul>{state.review.content.strengths.map((s,i)=><li key={i}>{s}</li>)}</ul></>}<h4>优先改这几处</h4><ol>{state.review.content.priorities.map((s,i)=><li key={i}>{s}</li>)}</ol>{state.review.content.dimensions.map(d=><p key={d.name}><b>{d.name}：</b>{d.comment}</p>)}{state.review.content.suggestions.map((s,i)=><article className="exam-revision" key={i}><p><b>你的原句：</b><span lang="en">{s.quote}</span></p><p><b>修改建议：</b><span lang="en">{s.replacement}</span></p><p>{s.reason}</p></article>)}</>:<><p role="status">{state.review?.message||"原稿已经保存，正在准备具体反馈…"}</p><button disabled={reviewBusy} onClick={()=>void review()}>{reviewBusy?"正在分析…":"重新获取分析"}</button></>}</section>}
        {feedback&&<div className="exam-actions"><button disabled={busy||reviewBusy||state.review?.status==="running"} onClick={()=>void save("restart")}>保留记录，重新作答</button><span className="exam-muted">已保留 {state.history_count+1} 轮提交。隔一段时间再做，检查是否真正掌握。</span></div>}
      </div>
    </div>
    <details className="exam-provenance"><summary>来源、核对范围与反馈说明</summary><p>{material.source_note} 核对日期：{material.checked_on}。</p><p>客观题按固定答案判题，解析由本站独立编写并对照原卷核对。写作、翻译反馈由模型生成，引用原稿的片段会检查是否真实存在。</p><p>原站完整文件可能包含参考答案，请先独立作答。读取失败时可在原站打开；本站不以替代音频冒充真题原音。</p><a href={material.source_url} target="_blank" rel="noreferrer">对应原卷 ↗</a>{feedback&&material.crosscheck_url&&<a href={material.crosscheck_url} target="_blank" rel="noreferrer">听力交叉核对来源（选项次序可能不同）↗</a>}</details>
  </section>;
}
