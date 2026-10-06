"use client";

import { useState } from "react";
import type { VocabularyTopic } from "@/lib/cet6";

export default function VocabularyTopicHelp({ topic }: { topic: VocabularyTopic }) {
  const [answers, setAnswers] = useState<Record<string, number>>({});
  return <aside className="cet6-topic-help" aria-label={`${topic.title}学习提示`}>
    <h3>{topic.title}</h3>
    <p>{topic.focus}</p>
    {topic.checks.length > 0 && <details>
      <summary>用一个小练习检查是否分清</summary>
      <p className="cet6-muted">本站自编用法练习。做完可以打开下方词卡，继续学习和收藏。</p>
      {topic.checks.map(check => <fieldset key={check.id}>
        <legend>{check.prompt}</legend>
        <div className="cet6-topic-options">{check.options.map((option, index) => <button type="button" key={option}
          aria-pressed={answers[check.id] === index} onClick={() => setAnswers(prev => ({ ...prev, [check.id]: index }))}>
          {String.fromCharCode(65 + index)}. {option}
        </button>)}</div>
        {answers[check.id] !== undefined && <div className="cet6-topic-feedback" role="status">
          <strong>{answers[check.id] === check.answer ? "这次分清了。" : `再对照一下：本题选 ${String.fromCharCode(65 + check.answer)}。`}</strong>
          <p>{check.explanation}</p>
          {!!check.sources.length && <p className="cet6-muted">用法依据：{check.sources.map((source, i) => <span key={source.url}>{i > 0 && " · "}<a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></span>)}</p>}
        </div>}
      </fieldset>)}
    </details>}
    {!!topic.reference_words.length && <details><summary>相关延伸词</summary><p className="cet6-muted">以下词暂未收录到本站词卡，可以打开词典搜索核对；下方列表只显示已有词卡。</p><div className="cet6-topic-references">{topic.reference_words.map(word => <a key={word} href={`https://www.oxfordlearnersdictionaries.com/search/english/direct/?q=${encodeURIComponent(word)}`} target="_blank" rel="noreferrer" lang="en">{word}</a>)}</div></details>}
  </aside>;
}
