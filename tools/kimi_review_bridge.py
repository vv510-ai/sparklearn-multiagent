"""Run a bounded Kimi Code review from an isolated, secret-free review packet.

Usage: python tools/kimi_review_bridge.py --kimi <kimi executable>
The packet contains only explicitly listed implementation files; no .env,
tokens, browser storage, user files, repository history or private data.
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kimi", default="kimi")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    folder = root / ".tmp" / "upgrade" / "kimi-review"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "empty-skills").mkdir(exist_ok=True)
    profile = folder / "reviewer.md"
    profile.write_text('---\nname: learnloop-reviewer\ndescription: Read-only code review\ntools: []\nsubagents: []\n---\nReview only the provided code. Report reproducible defects and identify missing context.\n', encoding="utf-8")
    functions = {
        "backend/app/services/model_preferences.py": ["_cipher", "_open", "_load", "save", "resolve"],
        "backend/app/services/study_research.py": ["research"],
        "backend/app/api/learning.py": ["english_scene", "followups"],
    }
    blocks = []
    for name, selected in functions.items():
        source = (root/name).read_text(encoding="utf-8")
        for node in ast.parse(source).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in selected:
                blocks.append(f"FILE: {name}:{node.lineno}\n{ast.get_source_segment(source, node)}")
    for name in ["backend/app/llm/selected_model.py", "backend/app/services/subtitle_service.py",
                 "backend/app/api/settings.py", "frontend/components/chat/AnswerChoices.tsx",
                 "frontend/app/api/[...path]/route.ts"]:
        blocks.append(f"FILE: {name}\n{(root/name).read_text(encoding='utf-8')}")
    packet = "\n\n".join(blocks)
    (folder / "packet.md").write_text(packet, encoding="utf-8")
    prompt = """请仅审查消息里给出的代码片段；这次是修复后的复审，不需要工具。
需求：每个账户独立选择 DeepSeek/Kimi/OpenAI 模型、密钥加密且不泄露；模型故障不能冒充成功；英语字幕场景不得伪造台词与来源；研究结果引用真实检索资料；聊天A-D按钮准确对应题目。
只报告具体可复现的 P1/P2 缺陷，给文件、原因、触发输入和最小修复建议。重点复核：保存版本冲突、原字幕定位时间、空研究计划、代理头信任。不要泛泛评价。代码片段缺少调用方时标记待核实，不猜实现。补充事实：当前日期2026-09-22，模型ID和价格已通过当天官方文档核验；不要根据旧训练知识判定新型号不存在。生产只有覆盖代理头的Nginx能访问Next容器；get_session_messages按账户过滤，error_label只返回错误白名单；统一网关优先解析所选模型，绝不在其故障后替换供应商。"""
    prompt += "\n\n" + packet
    if len(prompt) > 29000:
        raise RuntimeError("Review packet exceeds the Windows command-line budget")
    result = subprocess.run([args.kimi, "--agent-file", str(profile), "--skills-dir", str(folder / "empty-skills"),
                             "--prompt", prompt,
                             "--output-format", "text"], cwd=folder,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                            env={**os.environ, "KIMI_CODE_EXPERIMENTAL_FLAG": "1"})
    (folder / "review.txt").write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        (folder / "error.txt").write_text(result.stderr, encoding="utf-8")
    print(f"Kimi bridge exit={result.returncode}; review={folder / 'review.txt'}")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
