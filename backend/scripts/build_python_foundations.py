"""Build a new immutable course bundle; never alters the legacy textbook snapshot."""
from __future__ import annotations
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from urllib.request import urlopen
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.data.python_foundations import LESSONS
from import_python_textbook import Sections, BASE

EXTRA = {"interpreter": ["invoking-the-interpreter"],
         "datastructures": ["dictionaries", "tuples-and-sequences", "sets"],
         "modules": ["modules"], "inputoutput": ["reading-and-writing-files"],
         "errors": ["handling-exceptions", "syntax-errors"]}

def build(release_id: str, output: Path):
    if output.exists():
        raise ValueError("Refusing to overwrite a release; choose a new output and release ID")
    original = json.loads((ROOT / "app/data/textbooks/python_tutorial.json").read_text(encoding="utf-8"))
    sections = {s["id"]: dict(s) for s in original["sections"]}
    versions = {original["version"]}
    for page, anchors in EXTRA.items():
        html = urlopen(BASE + f"tutorial/{page}.html", timeout=30).read().decode("utf-8")
        versions.add(re.search(r"Python (3\.14\.\d+)", html)[1])
        parser = Sections()
        parser.feed(html)
        for anchor in anchors:
            text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "".join(parser.parts[anchor])).strip()
            if len(text) < 100:
                raise ValueError("Missing source: " + anchor)
            sections[anchor] = {"id": anchor, "title": parser.titles[anchor].strip(), "text": text,
                "url": BASE + f"tutorial/{page}.html#" + anchor,
                "sha256": hashlib.sha256(text.encode()).hexdigest(), "kps": []}
    if len(versions) != 1:
        raise ValueError(f"Mixed source versions: {versions}")
    lessons = []
    for key, title, objective, anchors, body, example, output, task, criteria, exercises in LESSONS:
        for anchor in anchors:
            sections[anchor]["kps"].append("foundation_" + key)
        questions = []
        for i, (code, expected, distractors, reason) in enumerate(exercises):
            options = [expected, *distractors]
            shift = (len(lessons) + i) % 4
            options = options[shift:] + options[:shift]
            questions.append({"id": key + "-" + str(i + 1), "stem": "合上讲解，独立判断下面程序的输出。",
                "code": code, "options": options, "answer": options.index(expected), "explanation": reason,
                "expected": expected, "source_sections": anchors})
        lessons.append({"id": key, "title": title, "objective": objective,
            "source_sections": anchors, "markdown": body,
            "example": {"code": example, "output": output}, "task": task, "criteria": criteria,
            "questions": questions, "review_prompt": "隔一天用下一道新题回忆，再解释代码为何得到该结果。",
            "authoring": "LearnLoop 原创，AI 辅助编写；已核对示例和来源，尚未经教学专家审定。"})
    wanted = {a for lesson in lessons for a in lesson["source_sections"]}
    selected = [s for key, s in sections.items() if key in wanted]
    for s in selected:
        s["kps"] = sorted(set(s["kps"]) & {"foundation_" + x["id"] for x in lessons})
    book = {**original, "id": "python-foundations-official-3.14", "course": "python_foundations",
        "sections": selected, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope_note": f"内置所列 {len(selected)} 个官方教程小节，配合本站 10 课入门导学；不覆盖整本官方教程。"}
    bundle = {"schema_version": 1, "course_id": "python_foundations", "release_id": release_id,
        "title": "Python 零基础入门", "description": "10 课，从运行第一段程序到完成学习记录统计。",
        "audience": "第一次系统学习编程的大学生与自学者", "prerequisites": "会使用电脑；准备可运行 Python 3 的环境。",
        "scope": "运行、变量、条件、循环、容器、函数、模块、文本文件、异常与综合任务。",
        "not_covered": "面向对象、网络开发、数据库、数据分析及学校特定考试范围。",
        "status_label": "10 课内容已备齐 · 开放试学",
        "review": {"method": "来源逐节核对、代码示例与新题执行验证；AI 辅助审查", "human_review": False,
                   "note": "未经过教学专家审定或真实学习效果验证，不作课程认证或成绩承诺。"},
        "rights": {"public_distribution": True, "basis": "Python PSF-2.0 / 示例另有 0BSD；本站原创导学与题目",
                   "license_notice": (ROOT / "app/data/textbooks/PYTHON-LICENSE.txt").read_text(encoding="utf-8")},
        "textbook": book, "lessons": lessons}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"lessons":len(lessons), "sections":len(selected), "source_version":book["version"], "output":str(output)},ensure_ascii=False))
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,96}", args.release_id):
        parser.error("Use a unique lowercase release ID (up to 96 characters)")
    build(args.release_id, args.output)
