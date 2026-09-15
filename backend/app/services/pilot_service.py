"""Teacher-owned, consented pilot observations; descriptive results only."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
import uuid
from collections import Counter, defaultdict
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from ..config import is_demo
from ..models.db import session
from ..models.entities import PilotObservation, PilotStudy
from .profile_service import ensure_user


class StudyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=120)
    course: str = Field(min_length=2, max_length=120)
    mode: Literal["demo", "field"] = "demo"
    protocol: str = Field(min_length=10, max_length=4000)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    participant: str = Field(pattern=r"^[A-Za-z0-9_-]{2,48}$")
    arm: Literal["intervention", "control"]
    phase: Literal["pre", "post", "delayed"]
    knowledge_point: str = Field(min_length=1, max_length=80)
    correct: int = Field(ge=0, le=10000, strict=True)
    total: int = Field(ge=1, le=10000, strict=True)
    independent: int = Field(ge=0, le=10000, strict=True)
    minutes: float = Field(gt=0, le=10000, allow_inf_nan=False)
    observed_on: dt.date
    consent: Literal[True]
    provenance: str = Field(min_length=4, max_length=300)
    data_kind: Literal["demo", "field"]
    errors: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def counts_match(self):
        if self.correct > self.total or self.independent > self.total:
            raise ValueError("correct and independent cannot exceed total")
        if self.observed_on > dt.datetime.now(dt.timezone.utc).date():
            raise ValueError("Observed date cannot be in the future")
        if any(not e.strip() or len(e) > 80 for e in self.errors):
            raise ValueError("Each error label must contain 1 to 80 characters")
        return self


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: list[Observation] = Field(min_length=1, max_length=1000)


def _study(db, user_id: str, study_id: str) -> PilotStudy:
    study = db.execute(select(PilotStudy).where(PilotStudy.id == study_id, PilotStudy.user_id == user_id)).scalars().first()
    if not study:
        raise HTTPException(404, "试点不存在")
    return study


def _pack(study: PilotStudy) -> dict:
    return {"id": study.id, "title": study.title, "course": study.course, "mode": study.mode,
            "protocol": study.protocol, "created_at": study.created_at.isoformat()}


def create_study(user_id: str, spec: StudyInput) -> dict:
    ensure_user(user_id)
    if is_demo() and spec.mode == "field":
        raise HTTPException(400, "离线演示只能建立演示试点")
    with session() as db:
        study = PilotStudy(id=uuid.uuid4().hex, user_id=user_id, **spec.model_dump())
        db.add(study); db.commit()
        return _pack(study)


def list_studies(user_id: str) -> list[dict]:
    with session() as db:
        return [_pack(s) for s in db.execute(select(PilotStudy).where(PilotStudy.user_id == user_id)
                .order_by(PilotStudy.created_at.desc())).scalars().all()]


def delete_study(user_id: str, study_id: str) -> dict:
    with session() as db:
        study = _study(db, user_id, study_id)
        db.execute(delete(PilotObservation).where(PilotObservation.user_id == user_id,
                                                 PilotObservation.study_id == study_id))
        db.delete(study)
        db.commit()
    return {"deleted": True}


def import_observations(user_id: str, study_id: str, spec: ImportInput) -> dict:
    # Validate the entire batch before writing; duplicates are idempotent and
    # conflicting observations are rejected instead of silently overwritten.
    with session() as db:
        study = _study(db, user_id, study_id)
        rows = db.execute(select(PilotObservation).where(PilotObservation.user_id == user_id,
                         PilotObservation.study_id == study_id)).scalars().all()
        index = {(r.participant, r.phase, r.knowledge_point): r.data for r in rows}
        arms = {r.participant: r.data["arm"] for r in rows}
        added = []
        duplicates = 0
        for item in spec.observations:
            data = item.model_dump(mode="json")
            if data["data_kind"] != study.mode:
                raise HTTPException(400, "演示与现场观测必须存放在不同试点")
            if data["participant"] in arms and arms[data["participant"]] != item.arm:
                raise HTTPException(400, "同一受试者不能同时属于实验组与对照组")
            arms[item.participant] = item.arm
            key = (item.participant, item.phase, item.knowledge_point)
            if key in index:
                if index[key] != data:
                    raise HTTPException(409, "已有同一受试者、阶段、知识点的不同记录；请先核对原始资料")
                duplicates += 1
                continue
            index[key] = data
            digest = hashlib.sha256(json.dumps([study_id, *key], ensure_ascii=False).encode()).hexdigest()
            added.append(PilotObservation(id=digest, user_id=user_id, study_id=study_id,
                         participant=item.participant, phase=item.phase, knowledge_point=item.knowledge_point, data=data))
        dates = defaultdict(dict)
        for (participant, phase, kp), data in index.items():
            dates[(participant, kp)][phase] = data["observed_on"]
        for stages in dates.values():
            ordered = [stages[p] for p in ("pre", "post", "delayed") if p in stages]
            if ordered != sorted(ordered) or ("delayed" in stages and "post" in stages and stages["delayed"] <= stages["post"]):
                raise HTTPException(400, "测量时间顺序错误：延迟测必须晚于后测")
        db.add_all(added)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "试点观测已被同时更新；请刷新并重试") from None
        return {"inserted": len(added), "duplicates": duplicates, "mode": study.mode,
                "verification": "用户导入，尚未独立核验"}


def study_report(user_id: str, study_id: str) -> dict:
    with session() as db:
        study = _pack(_study(db, user_id, study_id))
        data = [r.data for r in db.execute(select(PilotObservation).where(
            PilotObservation.user_id == user_id, PilotObservation.study_id == study_id)).scalars().all()]
    # Each student contributes one score per phase, avoiding a larger number
    # of submitted questions giving one student more influence than others.
    cells = defaultdict(list)
    for row in data:
        cells[(row["arm"], row["phase"], row["participant"])].append(row)
    scores = {}
    summaries = []
    for key, rows in cells.items():
        scores[key] = sum(r["correct"] for r in rows) / sum(r["total"] for r in rows)
    for arm in ("intervention", "control"):
        for phase in ("pre", "post", "delayed"):
            values = [v for (a,p,_),v in scores.items() if a == arm and p == phase]
            summaries.append({"arm": arm, "phase": phase, "n": len(values),
                              "mean_accuracy": statistics.mean(values) if values else None})
    paired = []
    gains = {}
    for arm in ("intervention", "control"):
        # Pair within participant AND knowledge point; unmatched topic sets
        # cannot produce a misleading improvement estimate.
        paired_topics = defaultdict(dict)
        for row in data:
            if row["arm"] == arm:
                paired_topics[(row["participant"], row["knowledge_point"])][row["phase"]] = row
        per_student = defaultdict(list)
        for (participant,_), phases in paired_topics.items():
            if "pre" in phases and "post" in phases:
                pre, post = phases["pre"], phases["post"]
                per_student[participant].append(post["correct"]/post["total"] - pre["correct"]/pre["total"])
        values = [statistics.mean(v) for v in per_student.values()]
        gains[arm] = statistics.mean(values) if values else None
        paired.append({"arm": arm, "n": len(values), "mean_gain": gains[arm]})
    heatmap = []
    for kp in sorted({r["knowledge_point"] for r in data}):
        rows = [r for r in data if r["knowledge_point"] == kp and r["phase"] == "post"]
        total = sum(r["total"] for r in rows)
        heatmap.append({"knowledge_point": kp, "n": len(rows),
            "accuracy": sum(r["correct"] for r in rows)/total if total else None,
            "errors": dict(Counter(e for r in rows for e in set(r.get("errors",[]))))})
    total = sum(r["total"] for r in data)
    return {"study": study, "observations": data, "participants": len({r["participant"] for r in data}),
            "summary": summaries, "paired": paired, "heatmap": heatmap,
            "independent_rate": sum(r["independent"] for r in data)/total if total else None,
            "difference_in_gains": gains["intervention"]-gains["control"] if all(v is not None for v in gains.values()) else None,
            "interpretation": "描述性汇总；缺测不补零。分组、量表等值性和原始凭证尚需研究负责人核验；不能直接作因果结论。",
            "verification": "演示数据，不代表教学效果" if study["mode"] == "demo" else "用户导入的现场观测，尚未独立核验"}
