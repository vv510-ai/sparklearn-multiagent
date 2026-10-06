"""Optional, reviewed study topics layered over the existing vocabulary identities."""
import copy
import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException


@lru_cache(maxsize=1)
def data():
    return json.loads((Path(__file__).parents[1] / 'data' / 'cet6_vocabulary_topics_v1.json').read_text(encoding='utf-8'))


def select(topic_id, entries):
    if not topic_id:
        return None
    topic = next((t for t in data()['topics'] if t['id'] == topic_id), None)
    if not topic:
        raise HTTPException(422, '学习专题不存在，请重新选择。')
    known = {e['word'] for e in entries.values()}
    result = copy.deepcopy(topic)
    result['reference_words'] = [w for w in result['words'] if w not in known]
    result['words'] = [w for w in result['words'] if w in known]
    return result


def catalogue(entries):
    known = {e['word'] for e in entries.values()}
    return [{'id': t['id'], 'title': t['title'], 'total': sum(w in known for w in t['words'])}
            for t in data()['topics']]
