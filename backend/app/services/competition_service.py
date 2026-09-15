"""Historical competition register for team material exports; no product API."""
from __future__ import annotations

import json

from ..config import DATA_DIR


GROUPS = [
    {"id": "growth", "name": "个人成长", "weight": 30, "page": 1},
    {"id": "innovation", "name": "项目创新", "weight": 30, "page": 1},
    {"id": "industry", "name": "产业价值", "weight": 25, "page": 2},
    {"id": "team", "name": "团队协作", "weight": 15, "page": 2},
]

_ROWS = [
    ("G1", "growth", "立德树人", "partial", "已有资料溯源、账号隔离、支持作答标识与独立复测。", "伦理与告知材料、内容审核记录、实践中的责任边界。", "backend/app/safety/guard.py"),
    ("G2", "growth", "调研深入", "missing", "修改方案提出调研建议，未发现可核验的原始调研数据。", "学生/教师/企业访谈、问卷原件、样本说明、调研改变产品的记录。", "docs/guochuang-2026/fieldwork.md"),
    ("G3", "growth", "逻辑正确", "partial", "数据结构课程、图谱、BKT与作答证据有实际代码。", "专业课程—问题发现—设计迭代—应用反馈的学生成长时间线。", "backend/app/services/bkt.py"),
    ("G4", "growth", "知识掌握与应用能力", "partial", "有可运行系统和工程验证。", "成员独立解释核心算法、开发记录、前后能力变化与真实成果。", "backend/tests"),
    ("G5", "growth", "人才培养成效", "missing", "未取得学校培育、孵化或产学研支持的证明。", "学校/导师支持凭证、课程或科研训练关联、指导记录。", "docs/guochuang-2026/team-ledger.md"),
    ("I1", "innovation", "问题导向", "partial", "已实现学、练、诊、补、测与路径调整。", "原型到真实课堂迭代的证据，验证每次改造解决的问题。", "backend/app/agents/eval_agent.py"),
    ("I2", "innovation", "目标导向", "partial", "面向高校专业课的独立掌握与下一步学习决策。", "目标学生和教师的真实需求及使用反馈。", "backend/app/services/path_service.py"),
    ("I3", "innovation", "创新成效", "partial", "证据引擎、补救、无提示复测与生成模型分工已实现。", "统一任务下的通用LLM/RAG/图谱/完整系统对比，教师盲评及成果权属。", "backend/app/services/learning_evidence.py"),
    ("V1", "industry", "产业认知", "missing", "当前没有足够一手行业和客户调研证据。", "带日期与来源的行业/竞品/采购访谈，避免杜撰市场规模。", "docs/guochuang-2026/fieldwork.md"),
    ("V2", "industry", "市场定位", "partial", "学生学习工作台与教师试点工作台，面向课程团队。", "付费意愿、采购流程、单位成本、服务边界和可行商业计划。", "frontend/app/teacher/page.tsx"),
    ("V3", "industry", "落地前景", "partial", "已有部署基础，新增匿名试点观测采集与汇总工具。", "真实班级持续应用、合作凭证、交付成本与盈利潜力证据。", "backend/app/services/pilot_service.py"),
    ("V4", "industry", "社会影响", "missing", "教育价值为待验证目标，不能由接口测试推断。", "真实学习效果、覆盖及可及性数据，就业等影响有则据实呈现。", "docs/guochuang-2026/study-protocol.md"),
    ("T1", "team", "团队精神", "partial", "已有协作开发说明，需与实际团队核对。", "共同使命、持续协作记录与问题解决案例。", "docs/协作开发说明.md"),
    ("T2", "team", "团队结构", "missing", "未核验成员配置、激励及实际分工。", "成员资格、专业结构、分工和决策机制；留学生参与属鼓励项。", "docs/guochuang-2026/team-ledger.md"),
    ("T3", "team", "团队效能", "partial", "有版本历史，无法单凭提交推断学生真实贡献。", "成员投入、任务成果、交接和现场问答证据。", "docs/guochuang-2026/team-ledger.md"),
    ("T4", "team", "团队资源", "missing", "未核验合作伙伴或资源承诺。", "与项目直接相关的合作、导师、场地及资源使用证明。", "docs/guochuang-2026/evidence-ledger.md"),
    ("T5", "team", "团队贡献", "missing", "现有技术实现不等于已证明每名成员和导师的实质贡献。", "成员/导师逐人任务、过程版本、独立产出与确认记录。", "docs/guochuang-2026/team-ledger.md"),
]


def register() -> dict:
    validation_path = DATA_DIR / "competition_validation.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else {}
    return {"project": "知行循证", "english_name": "LearnLoop",
        "full_name": "面向高校专业课程的可验证个性化学习平台",
        "track": "高教主赛道 · 本科生创意组 · 人工智能+", "as_of": "2026-09-15", "groups": GROUPS,
        "eligibility": "负责人已确认普通本科在读、未注册公司。需核验3—15名成员均为全日制在校本专科生、年龄、成果权属及往届获奖情况。正式报名截止2026年9月25日12时，学校截止时间另行核对。",
        "criteria": [{"id": i, "group": g, "title": t, "status": s, "baseline": b, "required_evidence": r, "implementation": p}
                     for i,g,t,s,b,r,p in _ROWS],
        "necessary_condition": {"status": "pending", "text": "科技成果、知识产权、财务、运营及荣誉等材料必须真实、准确、有效，完全符合申报条件；造假、抄袭等一票否决。"},
        "changes": ["调研过程及原始数据真实性", "课程、科研、实践与项目成长的逻辑联系", "成员和导师的实质性贡献", "关键事实的可追溯凭证"],
        "validation": validation,
        "field_results": [],
        "interpretation": "评分条款为质性评审标准。本页呈现证据覆盖，不预测分数；工程通过不代表教学效果。",
        "source": "评分依据：用户提供《2026评审规则》第1—2页。资格及分类依据：教育部教高函〔2026〕26号及附件1。规则变化PDF为辅助解读。",
        "official_url": "https://hudong.moe.gov.cn/srcsite/A08/s5672/202607/W020260731408855761133.pdf"}
