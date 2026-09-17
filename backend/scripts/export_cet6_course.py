"""Export the pinned original guide and scripts for reproducible speech assets."""
from __future__ import annotations

import json
import html
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from app.data.cet6_course import build_course, OFFICIAL_URL, GUIDE_URL  # noqa: E402


def main():
    course = build_course()
    path = ROOT / "docs/courses/cet6-guide-v1.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 小知六级起点学习指南（原创）", "", "版本：2026-09-v1。正文、例子、题目和听力脚本由本站编写，以 CC BY-SA 4.0 发布。", "",
        course["boundary"], "", "## 考试结构与课程范围", "",
        f"考试结构依据：[教育部教育考试院六级笔试介绍]({OFFICIAL_URL})，2026-09-18 核对。", "",
        "正式笔试共 130 分钟。写作占 15%（30 分钟）、听力占 35%（30 分钟）、阅读占 35%（40 分钟）、翻译占 15%（30 分钟）。", "",
        "本指南是分模块入门训练，短音频、三段匹配和句法辨析的篇幅不等于完整试卷。未引入历年真题全文，也不推断学习者的官方成绩。", "",
        "## 学习方法", "", "先做题确定当前卡点，再读例子，用不同的新题验证；按实际空闲时间安排两周任务。后续练习分三轮，分别使用新题，先间隔一天、再间隔三天检查。读过解析的题不算新的独立证据。", ""]
    for section in course["textbook"]["sections"]:
        lines += [f"## {section['id'].title()}", "", f"### {section['title']}", "", course["evidence"][section["kps"][0]][0]["text"], ""]
    lines += ["## 来源与许可", "", f"本页为原创教学资料，引用时注明[小知六级起点学习指南]({GUIDE_URL})及版本。许可：[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。", "",
        "官方页面只作为考试结构事实的出处；本站的练习和答案不是教育部教育考试院发布的试题。合成音频由 Windows System.Speech 英语语音按原创脚本离线生成；音频文件及脚本哈希记录在 backend/app/data/cet6_audio_manifest.json。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    # The repository is not publicly readable. Learners need a public source
    # page on the product itself; never send them to a private GitHub blob.
    sections = "".join(
        f'<section id="{s["id"]}"><h2>{html.escape(s["title"])}</h2>'
        + "".join(f"<p>{html.escape(p)}</p>" for p in course["evidence"][s["kps"][0]][0]["text"].split("\n\n")) + "</section>"
        for s in course["textbook"]["sections"])
    nav = " · ".join(f'<a href="#{s["id"]}">{html.escape(s["title"])}</a>' for s in course["textbook"]["sections"])
    public = ROOT / "frontend/public/courses/cet6-guide-v1.html"
    public.parent.mkdir(parents=True, exist_ok=True)
    public.write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>小知六级起点学习指南 · 2026-09-v1</title>
<style>body{margin:0;background:#f5f8f6;color:#203e34;font:17px/1.9 system-ui,sans-serif}main{max-width:820px;margin:auto;padding:32px 22px}h1{font-size:30px;line-height:1.4}h2{font-size:23px}a{color:#176b57}section{padding:16px 0;border-top:1px solid #cad9d1;scroll-margin-top:20px}nav{margin:24px 0}p{overflow-wrap:anywhere}small{color:#536a60}</style>
<main><a href="/">← 返回小知</a><h1>小知六级起点学习指南（原创）</h1><small>固定版本：2026-09-v1 · CC BY-SA 4.0</small>'''
        + f'<p>{html.escape(course["boundary"])}</p><p>正式笔试共 130 分钟：写作 15%（30 分钟）、听力 35%（30 分钟）、阅读 35%（40 分钟）、翻译 15%（30 分钟）。'
        + f'考试结构依据：<a href="{OFFICIAL_URL}" rel="noopener noreferrer">教育部教育考试院</a>，2026-09-18 核对。</p><nav aria-label="章节目录">{nav}</nav>'
        + sections + '<section><h2>来源与许可</h2><p>指南、例子、训练题与听力脚本为本站原创。练习使用合成英语音频，未引入历年真题全文。引用时请注明小知及版本。'
        + '<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0 许可</a>。</p></section></main></html>', encoding="utf-8")
    clips = [{"id": q["id"], "text": q["transcript"]} for q in course["bank"] + course["practice_bank"] if q.get("transcript")]
    scratch = ROOT / ".tmp/cet6-audio-input.json"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text(json.dumps(clips, ensure_ascii=False), encoding="utf-8")
    print(f"Exported 6 guide sections and {len(clips)} original listening scripts")


if __name__ == "__main__":
    main()
