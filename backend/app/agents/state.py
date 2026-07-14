"""全局 State(TypedDict):在 LangGraph 节点间流转;并行 fan-out 节点的更新通过
reducer 合并(列表追加 / 字典并入),fan-in 在 Eval Agent 汇总。"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dict(a: dict | None, b: dict | None) -> dict:
    out = dict(a or {})
    out.update(b or {})
    return out


class LearningState(TypedDict, total=False):
    # 会话身份
    user_id: str
    session_id: str
    # 输入
    messages: Annotated[list[dict], operator.add]      # [{role, content}]
    conversation: list[dict]                           # 持久化会话快照，不参与并行追加
    learning_goal: str
    knowledge_points: list[str]
    kinds: list[str]                                   # 期望生成的资源类型
    source_ids: list[str]                              # 指定上传资料
    prompt_template: str                              # 白名单学习模板键
    guided_learning: bool                             # 新主题由浅入深教学模式
    # 编排
    intent: str                                        # learn|summary|generate|tutor|eval|chat
    # 画像与计划
    student_profile: dict
    plan: dict                                         # Planner 输出
    path_plan: dict                                    # Path Agent 输出
    # 生成产物(并行节点合并)
    generated_resources: Annotated[dict, merge_dict]   # {resource_id: resource}
    retrieval_context: Annotated[list, operator.add]
    citations: Annotated[list, operator.add]
    safety_flags: Annotated[list, operator.add]
    progress_events: Annotated[list, operator.add]
    # 辅导直答
    answer: str
    tutor_extras: dict
