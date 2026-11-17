"""Pure, replayable policies. These functions never grant execution permissions."""

import hashlib
import math
import re


def tokens(text):
    text = text.casefold()
    # CJK bigrams plus Latin terms; avoid the English-only full-text pitfall.
    latin = re.findall(r"[a-z0-9_]+", text)
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    return set(
        latin
        + ([cjk] if len(cjk) == 1 else [cjk[i : i + 2] for i in range(len(cjk) - 1)])
    )


def relevance(query, text):
    q, t = tokens(query), tokens(text)
    lexical = len(q & t) / max(1, len(q))
    query_chars = set("".join(re.findall(r"[\w\u4e00-\u9fff]", query.casefold())))
    text_chars = set("".join(re.findall(r"[\w\u4e00-\u9fff]", text.casefold())))
    character_overlap = (
        2 * len(query_chars & text_chars)
        / max(1, len(query_chars) + len(text_chars))
    )
    vector = character_cosine(query, text)
    return round(
        min(1.0, max(lexical, character_overlap) * 0.68 + vector * 0.32),
        6,
    )


def character_vector(value, dimensions=256):
    normalized = "".join(re.findall(r"[\w\u4e00-\u9fff]+", value.casefold()))
    vector = [0.0] * dimensions
    for width in (1, 2, 3):
        for index in range(max(0, len(normalized) - width + 1)):
            shingle = normalized[index : index + width]
            digest = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest()
            number = int.from_bytes(digest, "big")
            bucket = number % dimensions
            vector[bucket] += 1.0 if number & 1 else -1.0
    magnitude = math.sqrt(sum(item * item for item in vector))
    return vector if magnitude == 0 else [item / magnitude for item in vector]


def character_cosine(left, right):
    a, b = character_vector(left), character_vector(right)
    return max(0.0, sum(x * y for x, y in zip(a, b)))


def rrf(*channels):
    scores = {}
    for channel in channels:
        for rank, id in enumerate(channel, 1):
            scores[id] = scores.get(id, 0) + 1 / (60 + rank)
    return sorted(scores, key=lambda id: (-scores[id], id))


def shallow_score(importance, references, age_days, tau=180):
    return importance * (1 + math.log1p(references)) * math.exp(-max(0, age_days) / tau)


def decay(value, baseline, hours, half_life=12):
    return baseline + (value - baseline) * 2 ** (-max(0, hours) / half_life)


def context(buckets, limit, count):
    """Adapter must supply the model's real token counter; no character/token equivalence."""
    required = [
        x
        for bucket, entries in buckets.items()
        if bucket in ("identity", "goal")
        for x in entries
    ]
    if sum(count(x) for x in required) > limit:
        raise ValueError("mandatory_context_overflow")
    result, omissions = required[:], 0
    used = sum(count(x) for x in result)
    for bucket, entries in buckets.items():
        if bucket in ("identity", "goal"):
            continue
        for x in entries:
            n = count(x)
            if used + n <= limit:
                result.append(x)
                used += n
            else:
                omissions += 1
    return {"entries": result, "tokens": used, "omissions": omissions}
