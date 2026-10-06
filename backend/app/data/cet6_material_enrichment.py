"""Reviewed teaching additions; original private course materials are not served."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def enrichment():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def enrich_papers(papers):
    for addition in enrichment()['reading']:
        paper = papers[addition['paper_id']]
        if paper['pdf_sha256'] != addition['source_sha256']:
            raise ValueError('Teaching notes require a review against the new source edition')
        by_number = {q['number']: q for q in addition['questions']}
        for kind in ('reading', 'reading_cloze', 'reading_matching', 'reading_careful'):
            for question in paper['blocks'].get(kind, {}).get('questions', []):
                note = by_number.get(question['number'])
                if note:
                    if note['answer'] != question['answer']:
                        raise ValueError('Teaching notes must not silently replace a published answer')
                    question.update(note)


def word_additions():
    return enrichment()['words']
