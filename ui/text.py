# ui/text.py
"""Render tables as plain fixed-width text, for the black-and-white UI."""

from __future__ import annotations

import math

import pandas as pd


def fmt(value, kind: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    if kind == "pct":
        return f"{value:.0f}%"
    if kind == "signed":
        return f"{value:+.0f}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def table(df: pd.DataFrame, columns: dict[str, tuple[str, str]], index_label: str | list[str] | None = None) -> str:
    """columns maps df column -> (header, kind). The index is printed first, left-aligned.

    Example output:
        color   games  score
        white      42    55%
        black      40    47%
    """
    if df.empty:
        return "No games."
    index_names = index_label if isinstance(index_label, list) else [index_label or (df.index.name or "")]
    index_rows = [list(i) if isinstance(i, tuple) else [i] for i in df.index]
    header = index_names + [h for h, _ in columns.values()]
    rows = [
        [str(v) for v in idx] + [fmt(row[col], kind) for col, (_, kind) in columns.items()]
        for idx, (_, row) in zip(index_rows, df.iterrows())
    ]
    n_index = len(index_names)
    widths = [max(len(r[i]) for r in [header] + rows) for i in range(len(header))]

    def line(cells):
        parts = [c.ljust(w) if i < n_index else c.rjust(w) for i, (c, w) in enumerate(zip(cells, widths))]
        return "  ".join(parts).rstrip()

    return "\n".join([line(header), line(["-" * w for w in widths])] + [line(r) for r in rows])
