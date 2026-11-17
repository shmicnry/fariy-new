"""Pure, replayable policies. These functions never grant execution permissions."""

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
    return len(q & t) / max(1, len(q))


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
