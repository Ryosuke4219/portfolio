"""差分計測ユーティリティ。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from statistics import median


def tokenize(text: str) -> list[str]:
    """簡易トークン化。"""

    return text.split()


def levenshtein_distance(a: Sequence[str], b: Sequence[str]) -> int:
    """レーベンシュタイン距離。"""

    if not a:
        return len(b)
    if not b:
        return len(a)

    prev_row = list(range(len(b) + 1))
    for i, token_a in enumerate(a, start=1):
        current_row = [i]
        for j, token_b in enumerate(b, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = prev_row[j] + 1
            replace_cost = prev_row[j - 1] + (0 if token_a == token_b else 1)
            current_row.append(min(insert_cost, delete_cost, replace_cost))
        prev_row = current_row
    return prev_row[-1]


def compute_diff_rate(output_a: str, output_b: str) -> float:
    """差分率を 0..1 で返す。"""

    tokens_a = tokenize(output_a)
    tokens_b = tokenize(output_b)
    if not tokens_a and not tokens_b:
        return 0.0
    distance = levenshtein_distance(tokens_a, tokens_b)
    return distance / max(len(tokens_a), len(tokens_b))


def summarize_diff_rates(diff_rates: Iterable[float]) -> float:
    """中央値を返す。空の場合は 0。"""

    data = list(diff_rates)
    if not data:
        return 0.0
    return float(median(data))
