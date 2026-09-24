"""Bounded SVG hierarchy + explicit learning navigation, using literal input text."""
from __future__ import annotations

import hashlib
import re
import uuid
from xml.sax.saxutils import escape


def map_plan(name, markdown):
    from .one_page_renderer import _plain, _width, _wrap
    title, intro, groups = name, [], []
    for raw in markdown.splitlines():
        if not raw.strip():
            continue
        if re.match(r"^#\s+", raw):
            title = _plain(re.sub(r"^#\s+", "", raw))
        elif re.match(r"^##\s+", raw):
            groups.append({"title": _plain(re.sub(r"^##\s+", "", raw)), "lines": []})
        elif raw.startswith("#") or raw.startswith(">") or "```" in raw or "|" in raw:
            return None
        elif groups:
            groups[-1]["lines"].append(_plain(re.sub(r"^(?:[-*] |[0-9]+[.、]\s*)", "", raw)))
        else:
            intro.append(_plain(raw))
    paths = [g for g in groups if re.search(r"学习(?:路径|顺序)|复习路径", g["title"])]
    if len(paths) > 1:
        return None
    nodes = [g for g in groups if g not in paths]
    if not 2 <= len(nodes) <= 6 or len(_wrap(title, 11)) > 3 or len(intro) > 1 or (intro and _width(intro[0]) > 58):
        return None
    for node in nodes:
        node["heading"] = _wrap(node["title"], 16)
        node["rows"] = [line for text in node["lines"] for line in _wrap(text, 19)]
        if not node["rows"] or len(node["heading"]) > 2 or len(node["rows"]) + len(node["heading"]) > 6:
            return None  # No clipping or smaller fonts to force a success.
    steps = []
    if paths:
        steps = [s.strip() for line in paths[0]["lines"] for s in line.split("→") if s.strip()]
        if not 2 <= len(steps) <= 5 or any(len(_wrap(s, 11)) > 3 for s in steps):
            return None
    return {"title": title, "intro": intro, "nodes": nodes, "paths": paths, "steps": steps}


def render_map(name, markdown, content_status, directory):
    from .one_page_renderer import _wrap
    plan = map_plan(name, markdown) if content_status != "source_excerpt" else None
    if plan is None:
        return None
    title, intro, nodes, paths, steps = (plan[k] for k in ("title", "intro", "nodes", "paths", "steps"))
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">',
        f'<title>{escape(title)} · 主题关系与学习路径</title>',
        '<defs><marker id="branch" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="none" stroke="#71958a" stroke-width="1.5"/></marker></defs>',
        '<rect width="1920" height="1080" fill="#FAF9F6"/>',
        '<g font-family="Microsoft YaHei, Noto Sans CJK SC, Arial, sans-serif">',
        '<text x="60" y="55" font-size="24" fill="#287257">LEARNLOOP · 一图看懂</text>',
        '<text x="1860" y="55" text-anchor="end" font-size="22" fill="#57736a">实线：主题分支　虚线：学习顺序</text>']
    texts = []
    def text_line(text, x, y, size=26, color="#22313F", weight=400, anchor="start", bounds=(0, 0, 1920, 1080)):
        texts.append(text)
        box = " ".join(f'data-bound-{key}="{value}"' for key,value in zip(("left","top","right","bottom"),bounds))
        parts.append(f'<text {box} data-content="true" xml:space="preserve" x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{escape(text)}</text>')
    if intro:
        text_line(intro[0], 960, 110, 28, anchor="middle")
    left = (len(nodes) + 1) // 2
    positions = []
    for side, subset in enumerate((nodes[:left], nodes[left:])):
        ys = {1: [375], 2: [220, 570], 3: [145, 385, 625]}[len(subset)]
        for node, y in zip(subset, ys):
            x = 60 if side == 0 else 1330
            start, target = (735, 590) if side == 0 else (1185, 1330)
            parts.append(f'<path data-relation="topic-branch" d="M{start},490 C{(start+target)/2},490 {(start+target)/2},{y+105} {target},{y+105}" fill="none" stroke="#71958a" stroke-width="3" marker-end="url(#branch)"/>')
            positions.append((node,x,y,side))
    parts.append('<rect x="735" y="395" width="450" height="190" rx="30" fill="#174c40"/>')
    for i, line in enumerate(_wrap(title, 11)):
        text_line(line, 960, 455 + i*45, 34, "#ffffff", 700, "middle", (759, 415, 1161, 565))
    parts.append('<text x="960" y="622" text-anchor="middle" font-size="24" fill="#57736a">先看主线，再沿分支理解</text>')
    colors = ["#2B6CB0", "#4B6B73", "#C46B28", "#7057A3", "#287257", "#496b9b"]
    for index,(node,x,y,side) in enumerate(positions):
        color = colors[index]
        parts.append(f'<rect x="{x}" y="{y}" width="530" height="218" rx="20" fill="white" stroke="{color}" stroke-width="2"/>')
        for i,line in enumerate(node["heading"]):
            text_line(line,x+24,y+44+i*34,29,color,700,bounds=(x+18,y+12,x+512,y+206))
        for i,line in enumerate(node["rows"]):
            text_line(line,x+24,y+48+len(node["heading"])*34+i*28,25,bounds=(x+18,y+12,x+512,y+206))
    if steps:
        text_line(paths[0]["title"], 60, 892, 26, "#287257", 700)
        width, gap = (1800 - 40*(len(steps)-1))/len(steps), 40
        for i,step in enumerate(steps):
            x=60+i*(width+gap)
            parts.append(f'<rect x="{x}" y="910" width="{width}" height="105" rx="18" fill="#eff6f1" stroke="#9eb9ac"/>')
            for j,line in enumerate(_wrap(step,11)):
                text_line(line,x+width/2,947+j*28,26,anchor="middle",bounds=(x+12,918,x+width-12,1011))
            if i:
                parts.append(f'<path data-relation="learning-order" d="M{x-gap},962 L{x-5},962" fill="none" stroke="#71958a" stroke-width="3" stroke-dasharray="6 5" marker-end="url(#branch)"/>')
    scope={"checked":"依据相关资料整理 · 出处与完整文字见笔记", "general_knowledge":"通用知识整理 · 未经课程资料核验", "supplemented":"资料优先，含通用补充 · 补充内容未经资料逐项核验"}[content_status]
    parts.extend([f'<text x="60" y="1057" font-size="21" fill="#57736a">{escape(scope)}</text>', '</g></svg>'])
    filename=f"one_page_{uuid.uuid4().hex}.svg"
    (directory/filename).write_text("\n".join(parts),encoding="utf-8")
    page={"title":name,"image_url":f"/static/gen/{filename}","image_status":"ready", "renderer":"svg-map-v2",
        "provider":"text_layout", "layout":"knowledge_map", "content_status":content_status,
        "relation_count":len(nodes)+max(0,len(steps)-1), "text_sha256":hashlib.sha256("".join(texts).encode()).hexdigest()}
    return {**page,"pages":[page],"markdown_sha256":hashlib.sha256(markdown.encode()).hexdigest()}
