"""Bounded public-source research. Search excerpts are never called full papers."""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import re

import httpx

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt


def clean(value: str, limit: int = 2500) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))[:limit].strip()


async def _encyclopedia(client: httpx.AsyncClient, query: str) -> list[dict]:
    response = await client.get("https://en.wikipedia.org/w/api.php", params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": query,
        "gsrlimit": 2, "prop": "extracts|info", "explaintext": 1, "exintro": 1,
        "exchars": 2500, "inprop": "url"})
    response.raise_for_status()
    return [{"title": p["title"], "url": p["fullurl"], "excerpt": clean(p.get("extract", "")),
             "kind": "百科导言", "published_at": None, "query": query}
            for p in response.json().get("query", {}).get("pages", {}).values()
            if p.get("fullurl") and p.get("extract")]


async def _papers(client: httpx.AsyncClient, query: str) -> list[dict]:
    response = await client.get("https://api.crossref.org/works", params={"query.bibliographic": query, "rows": 2,
        "select": "title,DOI,abstract,published,URL,type"})
    response.raise_for_status()
    results = []
    for p in response.json().get("message", {}).get("items", []):
        if not p.get("title") or not p.get("URL", "").startswith("https://doi.org/"):
            continue
        dates = p.get("published", {}).get("date-parts", [[]])[0]
        results.append({"title": clean(p["title"][0], 300), "url": p["URL"],
                        "excerpt": clean(p.get("abstract", "")),
                        "kind": "论文摘要" if p.get("abstract") else "论文题录（未取得摘要）",
                        "published_at": "-".join(str(x) for x in dates) or None, "query": query})
    return results


async def discover(queries: list[str]) -> tuple[list[dict], list[str]]:
    sources, failures, seen = [], [], set()
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers={"User-Agent": "LearnLoop-Education/1.0"}) as client:
        jobs = [(name, query, fn(client, query)) for query in queries[:3]
                for name, fn in [("Wikipedia", _encyclopedia), ("Crossref", _papers)]]
        results = await asyncio.gather(*(job[2] for job in jobs), return_exceptions=True)
    for (name, _, _), result in zip(jobs, results):
        if isinstance(result, Exception):
            failures.append(name + " 检索暂不可用")
            continue
        for item in result:
            if item["url"] not in seen:
                seen.add(item["url"])
                item.update(id=len(sources) + 1, retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat())
                sources.append(item)
    return sources, sorted(set(failures))


async def research(question: str, *, offline: bool = False) -> dict:
    plan = {"questions": [question, "理解运行机制", "比较适用条件与反例"], "queries": [question]}
    if not offline:
        call = invoke_learning_prompt("research.plan", question=question)
        try:
            data = parse_json(await llm_complete(call.prompt, system=call.system, json_object=True,
                max_tokens=700, reasoning_mode="disabled", allow_mock_fallback=False, allow_model_fallback=False))
            raw_queries, raw_questions = data.get("queries"), data.get("questions")
            queries = [q.strip()[:120] for q in raw_queries if isinstance(q, str) and q.strip()][:3] if isinstance(raw_queries, list) else []
            if queries:
                questions = [q.strip()[:200] for q in raw_questions if isinstance(q, str) and q.strip()][:3] if isinstance(raw_questions, list) else []
                plan = {"questions": questions or plan["questions"], "queries": queries}
        except (ValueError, TypeError, AttributeError, RuntimeError):
            pass  # Exact user query remains a valid, disclosed search plan.
    if offline:
        return {"plan": plan, "sources": [], "status": "offline", "limitations": ["离线演示未进行联网检索"],
                "markdown": "## 研究计划\n\n" + "\n".join(f"* {q}" for q in plan["questions"]) + "\n\n离线模式仅展示研究计划，不生成无来源的研究结论。"}
    sources, failures = await discover(plan["queries"])
    readable = [s for s in sources if s["excerpt"]]
    if not readable:
        return {"plan": plan, "sources": sources, "status": "insufficient_evidence", "limitations": failures,
                "markdown": "## 证据不足\n\n当前未取得可阅读的内容，不能据此生成研究结论。可打开下方来源或调整检索词后重试。"}
    evidence = json.dumps(readable, ensure_ascii=False)
    call = invoke_learning_prompt("research.report", question=question, plan=json.dumps(plan, ensure_ascii=False), evidence=evidence)
    try:
        report = await llm_complete(call.prompt, system=call.system, max_tokens=4500,
                                    allow_mock_fallback=False, allow_model_fallback=False)
    except RuntimeError:
        return {"plan": plan, "sources": sources, "status": "sources_only", "limitations": failures + ["模型暂不可用，已保留真实检索结果"],
                "markdown": "## 已找到学习资料\n\n报告生成失败。下方来源与片段可以直接阅读，未使用演示结论替代模型报告。"}
    valid_ids = {str(s["id"]) for s in readable}
    cited = set(re.findall(r"\[(\d+)\]", report))
    if not cited or cited - valid_ids:
        return {"plan": plan, "sources": sources, "status": "sources_only", "limitations": failures + ["报告引用检查未通过，保留原始来源供阅读"],
                "markdown": "## 已找到学习资料\n\n生成报告没有提供可核对的来源编号，暂不展示结论。"}
    return {"plan": plan, "sources": sources, "status": "complete", "markdown": report,
            "limitations": failures + ["本轮最多3个检索词、12条来源；百科导言和论文摘要不等于全文；编号有效不代表结论已独立核验。"]}
