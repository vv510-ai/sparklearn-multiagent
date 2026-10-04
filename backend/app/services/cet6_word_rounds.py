"""Finite, resumable recall rounds; progress comes from committed card attempts."""
from __future__ import annotations

import copy
import re
from sqlalchemy import select, update
from fastapi import HTTPException

from ..models.db import session
from ..models.entities import VocabularyCard, VocabularyDay
from . import cet6_learning as learning, cet6_word_plan as plan, cet6_vocabulary as vocabulary
from .vocabulary_lessons import preferred_sense


def _cards(db, user, notebook):
    return {(c.entry_id, c.sense_id): c for c in db.scalars(select(VocabularyCard).where(
        VocabularyCard.user_id == user, VocabularyCard.notebook_id == notebook)).all()}


def _public(value, cards):
    result = copy.deepcopy(value)
    for item in result['items']:
        row = cards.get((item['entry_id'], item['sense_id']))
        track = row.data.get('tracks', {}).get(item['mode'], {}) if row else {}
        item['done'] = track.get('attempts', 0) > item['attempts']
    result['completed'] = sum(i['done'] for i in result['items'])
    result['total'] = len(result['items'])
    result['finished'] = result['completed'] == result['total']
    return result


def detail(user, notebook, round_id):
    learning.check(user, notebook)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}:[0-9a-f-]{36}', round_id):
        raise HTTPException(404, '这轮词卡不存在。')
    with session() as db:
        row = db.get(VocabularyDay, learning.stable_id('word-day', user, notebook, round_id[:10]))
        value = next((r for r in row.data.get('rounds', []) if r['id'] == round_id), None) if row else None
        if value is None:
            raise HTTPException(404, '这轮词卡不属于当前课程。')
        return _public(value, _cards(db, user, notebook))


def start(user, notebook, kind, request_id):
    learning.check(user, notebook)
    today = plan.today(user, notebook)
    round_id = f"{today['day']}:{request_id}"
    day_id = learning.stable_id('word-day', user, notebook, today['day'])
    for _ in range(4):
        with session() as db:
            cards = _cards(db, user, notebook)
            days = db.scalars(select(VocabularyDay).where(VocabularyDay.user_id == user,
                VocabularyDay.notebook_id == notebook).order_by(VocabularyDay.day.desc())).all()
            # A lost response reuses the same round, including after completion.
            for day in days:
                for value in reversed(day.data.get('rounds', [])):
                    if value['id'].split(':', 1)[1] == str(request_id):
                        if value['kind'] != kind:
                            raise HTTPException(409, '请求标识已用于另一种练习。')
                        return _public(value, cards)
            for day in days:
                for value in reversed(day.data.get('rounds', [])):
                    current = _public(value, cards)
                    if value['kind'] == kind and not current['finished']:
                        return current
            items = []
            if kind == 'new':
                for entry_id in today['new_ids']:
                    e = vocabulary.entry(entry_id)
                    siblings = [c for (item, _), c in cards.items() if item == entry_id]
                    if any(c.data.get('tracks') or c.data.get('queued_at') for c in siblings):
                        continue
                    active = next((c for c in siblings if c.data.get('active')), None)
                    sense = active.sense_id if active else preferred_sense(e)
                    items.append(dict(entry_id=entry_id, sense_id=sense,
                        mode=active.data['active']['mode'] if active else 'meaning', attempts=0))
                    if len(items) == 5:
                        break
            else:
                now = learning.now().isoformat()
                due = sorted((track['due_at'], c.entry_id, c.sense_id, mode, track)
                    for c in cards.values() for mode, track in c.data.get('tracks', {}).items()
                    if track.get('due_at', 'z') <= now
                    and (not c.data.get('active') or c.data['active']['mode'] == mode))
                due += [(c.data['queued_at'], c.entry_id, c.sense_id, 'meaning', {}) for c in cards.values()
                    if c.data.get('queued_at', 'z') <= now and not c.data.get('tracks', {}).get('meaning')
                    and (not c.data.get('active') or c.data['active']['mode'] == 'meaning')]
                due.sort(key=lambda item: item[:4])
                for _, entry_id, sense, mode, track in due[:20]:
                    items.append(dict(entry_id=entry_id, sense_id=sense, mode=mode, attempts=track.get('attempts', 0)))
            value = dict(id=round_id, kind=kind, created_at=learning.now().isoformat(), items=items)
            if not items:
                return _public(value, cards)
            day = next(d for d in days if d.id == day_id)
            data = copy.deepcopy(day.data)
            data.setdefault('rounds', []).append(value)
            changed = db.execute(update(VocabularyDay).where(VocabularyDay.id == day_id,
                VocabularyDay.user_id == user, VocabularyDay.revision == day.revision)
                .values(data=data, revision=day.revision + 1))
            if changed.rowcount != 1:
                db.rollback()
                continue
            db.commit()
            return _public(value, cards)
    raise HTTPException(409, '另一页面正在开启词卡，请重试。')
