"""Presentation and evidence checks for newly generated course questions only."""
from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json
import random
import re

CONTRACT_VERSION = "course-quality-2026-09-24-v2"


def position_dependent(text: str) -> bool:
    # These options cannot be permuted without changing their meaning.
    explicit = re.search(r"以上(?:都|均|皆)|上述(?:选项|各项)|前[两二三]项|第[一二三四五1-5]+个选项|(?:选项|答案)\s*[A-E]|[A-E]\s*(?:选项|项(?:正确|错误|和|与))", text)
    # Matrix/set variables in a sentence are not references to choice positions.
    letters_only = re.fullmatch(r"\s*[A-E]\s*(?:和|与|、|/|and|or)\s*[A-E](?:\s*(?:和|与|、|/|and|or)\s*[A-E])*(?:都|均)?(?:正确|错误|成立)?[。.]?\s*", text)
    return bool(explicit or letters_only)


def balance_options(course: dict) -> None:
    """Reorder before blind solving, keeping IDs and option/key identity together."""
    bank = course["bank"]
    seed = hashlib.sha256(json.dumps([(q["id"], q["stem"], q["options"]) for q in bank], ensure_ascii=False).encode()).digest()
    rng = random.Random(seed)
    global_use, local_use = Counter(), Counter()
    for q in bank:
        options = q["options"]
        labels = list("ABCDE"[:len(options)])
        correct = set(q["answer"] if isinstance(q["answer"], list) else [q["answer"]])
        candidates = list(itertools.combinations(range(len(options)), len(correct)))
        def cost(slots):
            return (sum(local_use[(q["kp"], q["type"], i)] for i in slots),
                    sum(global_use[(q["type"], i)] for i in slots))
        best = min(map(cost, candidates))
        slots = rng.choice([c for c in candidates if cost(c) == best])
        right = [i for i, label in enumerate(labels) if label in correct]
        wrong = [i for i, label in enumerate(labels) if label not in correct]
        rng.shuffle(right)
        rng.shuffle(wrong)
        order = [right.pop() if i in slots else wrong.pop() for i in range(len(options))]
        q["options"] = [options[i] for i in order]
        answers = [labels[i] for i in slots]
        q["answer"] = answers if q["type"] == "multiple" else answers[0]
        q["explain"] = "等待独立逐项复核后提供解析。"
        for i in slots:
            local_use[(q["kp"], q["type"], i)] += 1
            global_use[(q["type"], i)] += 1


def evidence_statements(chunks: list[dict]) -> dict[str, dict]:
    result = {}
    for chunk in chunks:
        pieces = [text.strip() for text in re.split(r"(?<=[。！？；\n])", chunk["text"]) if text.strip()]
        for index, text in enumerate(pieces, 1):
            key = f"{chunk['evidence_id']}:{index}"
            result[key] = {"id": key, "chunk_id": chunk["evidence_id"], "text": text}
    return result


def evidence_valid(row: dict, question: dict, chunks: list[dict]) -> bool:
    if not chunks:
        return row.get("evidence") == []
    evidence = row.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    statements = evidence_statements(chunks)
    return all(isinstance(key, str) and key in statements
        and statements[key]["chunk_id"] in question.get("evidence_ids", []) for key in evidence)
