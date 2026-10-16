"""BKT 贝叶斯知识追踪:每个知识点维护掌握概率 p(L),按答题对错贝叶斯更新。

参数:p_init 先验掌握、p_learn 练习后习得、p_slip 会而做错、p_guess 不会蒙对。
公式(标准 BKT, Corbett & Anderson 1994):
  先验 p = p(L_t)
  答对: p_obs = p(1-slip) / [p(1-slip) + (1-p)guess]
  答错: p_obs = p·slip / [p·slip + (1-p)(1-guess)]
  更新: p(L_{t+1}) = p_obs + (1-p_obs)·p_learn

BKT⁺(本项目扩展,全部为可解释的确定性规则):
1. 情境化猜测/失误率(Baker et al., ITS 2008):单选的猜测率≈1/选项数,判断题 0.5,
   填空与简答很难蒙对;同一次“答对”在不同题型下提供的证据强度不同。
2. 支持程度分级:借助提示后答对只算弱证据(猜测率抬高到 ≥0.5);看过答案的作答由调用方
   记为未独立答对,不会抬高掌握度。
3. 遗忘衰减(BKT-Forget, Nedungadi & Remya 2014;时间效应 Qiu et al., UMAP 2011):
   距上次证据的天数 Δt 内,掌握度向先验回落 p ← p0 + (p - p0)·2^(-Δt/h),
   半衰期 h 随累计独立答对次数增长(7 天 × 1.6^n,上限 180 天),复习越多忘得越慢。
"""
from __future__ import annotations

from dataclasses import dataclass

FORGET_FLOOR = 0.30          # 回落到课程先验,而不是归零:学过的内容不会完全消失
BASE_HALF_LIFE_DAYS = 7.0
HALF_LIFE_GROWTH = 1.6
MAX_HALF_LIFE_DAYS = 180.0
MIN_DECAY_DAYS = 1 / 24       # 一小时内的连续作答不衰减


@dataclass
class BKTParams:
    p_init: float = 0.30
    p_learn: float = 0.20
    p_slip: float = 0.10
    p_guess: float = 0.20


def bkt_update(p_mastery: float, correct: bool, params: BKTParams | None = None) -> float:
    pm = params or BKTParams()
    p = min(max(p_mastery, 1e-6), 1 - 1e-6)
    if correct:
        num = p * (1 - pm.p_slip)
        den = num + (1 - p) * pm.p_guess
    else:
        num = p * pm.p_slip
        den = num + (1 - p) * (1 - pm.p_guess)
    p_obs = num / den if den > 0 else p
    return round(p_obs + (1 - p_obs) * pm.p_learn, 4)


def contextual_params(item_type: str = "", options: int = 0, support: str = "independent") -> BKTParams:
    """Guess/slip by question type and help level (contextual BKT)."""
    kind = str(item_type or "").lower()
    if kind in {"single", "complexity", "choice"}:
        guess = 1 / options if options >= 2 else 0.25
        slip = 0.10
    elif kind in {"judge", "truefalse", "true_false"}:
        guess, slip = 0.50, 0.08
    elif kind in {"fill", "short", "design", "code", "open"}:
        guess, slip = 0.05, 0.15
    else:
        guess, slip = 0.20, 0.10
    if support == "hinted":
        guess = max(guess, 0.50)   # a hint makes success much less diagnostic
    return BKTParams(p_guess=round(guess, 4), p_slip=slip)


def half_life_days(independent_correct: int) -> float:
    return min(MAX_HALF_LIFE_DAYS, BASE_HALF_LIFE_DAYS * HALF_LIFE_GROWTH ** max(0, int(independent_correct)))


def forget(p_mastery: float, days: float | None, independent_correct: int = 0, floor: float = FORGET_FLOOR) -> float:
    """Exponential decay toward the prior since the last piece of evidence."""
    if days is None or days < MIN_DECAY_DAYS or p_mastery <= floor:
        return p_mastery
    factor = 2 ** (-float(days) / half_life_days(independent_correct))
    return round(floor + (p_mastery - floor) * factor, 4)


def bkt_update_plus(p_mastery: float, correct: bool, *, item_type: str = "", options: int = 0,
                    support: str = "independent", days_since: float | None = None,
                    independent_correct: int = 0) -> float:
    """Forget first (time since last evidence), then a contextual Bayesian update."""
    prior = forget(p_mastery, days_since, independent_correct)
    return bkt_update(prior, correct, contextual_params(item_type, options, support))


def predicted_correct(p_mastery: float, params: BKTParams | None = None) -> float:
    """P(next answer correct) = p(1-slip) + (1-p)guess — used for ZPD targeting."""
    pm = params or BKTParams()
    p = min(max(p_mastery, 0.0), 1.0)
    return round(p * (1 - pm.p_slip) + (1 - p) * pm.p_guess, 4)


def mastery_level(p: float) -> str:
    if p >= 0.8:
        return "掌握"
    if p >= 0.5:
        return "进行中"
    return "薄弱"
