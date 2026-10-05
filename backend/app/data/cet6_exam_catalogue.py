"""Source metadata and keys only. Full documents remain on their external origin."""
import copy
import json
from functools import lru_cache
from pathlib import Path
from .cet6_exam_pilot import pilot
from .cet6_material_enrichment import enrich_papers

READING_TYPES = {
    'reading_cloze': ('选词填空', 26, 35, 10),
    'reading_matching': ('段落匹配', 36, 45, 10),
    'reading_careful': ('仔细阅读', 46, 55, 20),
}


@lru_cache(maxsize=1)
def catalogue_data():
    path = Path(__file__).with_name('cet6_exam_catalogue_v2.json')
    values = json.loads(path.read_text(encoding='utf-8'))['papers'] if path.exists() else []
    papers = {p['id']: p for p in values}
    first = pilot()
    if first['id'] in papers:
        # Keep the already published 30-question legacy attempt and its answers.
        for kind in ['reading', 'listening', 'writing', 'translation']:
            papers[first['id']]['blocks'][kind] = first['blocks'][kind]
        # Retain the reviewed teaching notes in the three new independent rounds.
        notes = {q['number']: q for q in first['blocks']['reading']['questions']}
        for kind in READING_TYPES:
            for q in papers[first['id']]['blocks'].get(kind, {}).get('questions', []):
                q.update({k: copy.deepcopy(v) for k, v in notes[q['number']].items()
                          if k not in {'page', 'group'}})
        papers[first['id']]['unavailable'].pop('listening', None)
        papers[first['id']]['version'] = first['version']
    else:
        papers[first['id']] = first
    for paper in papers.values():
        reading = paper['blocks'].get('reading')
        if reading:
            for kind, (title, start, end, minutes) in READING_TYPES.items():
                if kind in paper['blocks']:
                    continue
                questions = [copy.deepcopy(q) for q in reading['questions'] if start <= q['number'] <= end]
                # Include the whole original reading section for reliable paragraph extraction.
                paper['blocks'][kind] = dict(title=title, minutes=minutes,
                    pages=reading['pages'], questions=questions)
    enrich_papers(papers)
    return papers
