"""Pick bounded query-relevant passages with exact original character ranges."""

import re


def excerpt(text, query, limit=5000):
    if len(text) <= limit:
        return {
            "content": text,
            "ranges": [{"start": 0, "end": len(text)}],
            "is_excerpt": False,
            "source_characters": len(text),
        }
    terms = set(re.findall(r"[A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", query.casefold()))
    for token in list(terms):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            terms.update(token[index : index + 2] for index in range(len(token) - 1))
    terms = sorted(terms, key=len, reverse=True)[:32]
    ranked = []
    actions = re.compile(
        r"排查步骤|只读排查|最小取证链|补证建议|验证标准|恢复前提|(?i:troubleshooting|verification steps)"
    )
    for start in range(0, len(text), 600):
        end = min(len(text), start + 800)
        block = text[start:end].casefold()
        score = sum((10 + len(term) if re.search(r"[a-z0-9]", term) else len(term)) for term in terms if term in block)
        ranked.append((score, start, end))
    # Matching a code alone omits the later procedure that makes its diagnosis useful.
    # Keep bounded original passages rather than synthesizing advice from a keyword.
    if any(score for score, _, _ in ranked):
        for match in list(actions.finditer(text))[:8]:
            start = match.start()
            end = min(len(text), start + 800)
            ranked.append((1, start, end))
    chosen = []
    remaining = limit
    for score, start, end in sorted(ranked, key=lambda row: (-row[0], row[1])):
        if chosen and score == 0:
            break
        if any(start < other[1] and end > other[0] for other in chosen):
            continue
        header = f"【原文字符 {start}–{end}】\n"
        if len(header) + end - start + 2 > remaining:
            continue
        chosen.append((start, end, header))
        remaining -= len(header) + end - start + 2
        if len(chosen) >= 5:
            break
    if not chosen:
        chosen = [(0, min(limit - 40, len(text)), "【原文起始摘录】\n")]
    chosen.sort()
    return {
        "content": "\n\n".join(header + text[start:end] for start, end, header in chosen),
        "ranges": [{"start": start, "end": end} for start, end, _ in chosen],
        "is_excerpt": True,
        "source_characters": len(text),
    }
