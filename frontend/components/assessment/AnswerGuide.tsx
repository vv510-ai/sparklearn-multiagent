"use client";

import { useState } from "react";

export default function AnswerGuide() {
  const [choice, setChoice] = useState("");
  const [submitted, setSubmitted] = useState(false);
  return <details className="answer-guide">
    <summary>第一次使用？先试一下怎么回答（不计分）</summary>
    <p>① 读题。② 点击选项整行，单选选一个，多选可以选几个。③ 点击“提交，继续下一题”。</p>
    <fieldset disabled={submitted}>
      <legend>操作演示：任选一句话，试着提交</legend>
      {["我准备好了", "我想慢慢来"].map((text, i) => <label key={text}>
        <input type="radio" name="answer-demo" checked={choice === text} onChange={() => setChoice(text)} />
        <span>{String.fromCharCode(65 + i)}. {text}</span>
      </label>)}
    </fieldset>
    {submitted ? <p role="status">操作练习完成。这两项都没有对错，也不会计入测评。正式题目不会时，可以选“这题还不会”或“暂时跳过此题”。</p>
      : <button type="button" className="secondary-action" disabled={!choice} onClick={() => setSubmitted(true)}>提交演示答案</button>}
  </details>;
}
