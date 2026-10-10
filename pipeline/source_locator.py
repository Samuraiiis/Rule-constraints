"""引文定位：把一段 `source_text` 映射回它在输入 Markdown 中的位置与所在页。

质检门（`agent_generated/scripts/check_agent_raw.py`）和页码清洗
（`scripts/clean_page_field.py`）必须用**同一套**归一化与定位规则，否则清洗出来的
page 会被质检门判成"与引文实际所在页不符"。归一化只做：NFC + 引号/破折号/软连字
等价 + 剥离页码 marker + OCR 噪声（$...$、[[...]]、图片语法）+ 空白折叠 + 小写。
**不做**缩写展开与同义替换——原文写 TTP 而 mention 写全称就是不一致。
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from pipeline.page_marker import PAGE_MARKER_RE, extract_pdf_page

# 归一化时被剥掉的 OCR/LaTeX 噪声（只影响比对，不改数据）
# 开头的 $ 不能是 \$（转义的货币符号，如 \$60 million），否则会把货币符号当成
# LaTeX 定界符，把正文吞成噪声。
NOISE_RE = re.compile(r"(?<!\\)\$[^$]*(?<!\\)\$|\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)")
TRANSLIT = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "‑": "-", "­": "", " ": " ",
    "ﬁ": "fi", "ﬂ": "fl", "…": "...",
}


def normalize(text: str, *, strip_pages: bool = False) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    for src, dst in TRANSLIT.items():
        t = t.replace(src, dst)
    if strip_pages:
        t = PAGE_MARKER_RE.sub(" ", t)
    t = NOISE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def load_markdown(input_path: Path) -> str:
    return input_path.read_text(encoding="utf-8")


_EDGE_PUNCT = ".,;:!?()[]{}\"'‘’“”-–—/\\`"


def words(normalized_text: str) -> list[str]:
    """归一化串切词：剥掉词边缘标点，保证 `controls` 能匹配句末的 `controls.`。

    只做标点剥离，不合并连字符（first-episode 与 first episode 仍不相等）——
    归一化口径越窄，质检门越不会因为自己的改写而误判。
    """
    return [t.strip(_EDGE_PUNCT) for t in normalized_text.split()]


def contains_phrase(short_norm: str, long_norm: str) -> bool:
    """short 是否作为连续整词片段出现在 long 中（不看裸子串）。

    裸子串会把 `ACC` 判成出现在 `accuracy of eye movements` 里，反之也会把
    缩写当成全称命中，所以这里按词比对。
    """
    a, b = words(short_norm), words(long_norm)
    if not a or len(a) > len(b):
        return False
    return any(b[k:k + len(a)] == a for k in range(len(b) - len(a) + 1))


def pdf_page_sequence(raw: str) -> list[int]:
    """按出现顺序取所有 marker 的 PDF 页序号（与 pipeline.page_marker 同口径，带偏移版）。"""
    return [extract_pdf_page(m.group(0)) for m in PAGE_MARKER_RE.finditer(raw)]


def marker_offsets(raw: str) -> list[tuple[int, int]]:
    """返回 [(marker 结束偏移, PDF 页序号)]，顺序即出现顺序。"""
    return [(m.end(), extract_pdf_page(m.group(0))) for m in PAGE_MARKER_RE.finditer(raw)]


def page_at(offset: int, markers: list[tuple[int, int]]) -> int | None:
    """正文偏移 offset 落在哪一页：取最后一个"marker 结束位置 <= offset"的页号。

    第一个 marker 之前的正文（标题/作者行）没有页归属 → None。
    """
    page: int | None = None
    for end, num in markers:
        if end <= offset:
            page = num
        else:
            break
    return page


class SourceIndex:
    """归一化正文 + 「归一化偏移 → 原始偏移」映射，用于把引文定位回原页。"""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.markers = marker_offsets(raw)
        self.norm_text, self.norm_to_raw = self._build(raw)

    @staticmethod
    def _build(raw: str) -> tuple[str, list[int]]:
        """逐字符重建归一化串，同时记录每个归一化字符来自原始串的哪个下标。

        不能用 `normalize(raw)` 直接得到文本再去找——那样拿不到偏移。这里按 normalize
        的规则手工走一遍：marker 与噪声整段跳过，TRANSLIT 一对一/多对一映射，空白折叠。
        """
        out: list[str] = []
        origins: list[int] = []
        i, n = 0, len(raw)
        pending_space = False
        pending_at = -1

        def flush_space(pos: int) -> None:
            nonlocal pending_space, pending_at
            if pending_space and out and out[-1] != " ":
                out.append(" ")
                origins.append(pos)
            pending_space = False

        while i < n:
            ch = raw[i]

            m = PAGE_MARKER_RE.match(raw, i)
            if m:
                pending_space = True
                pending_at = pending_at if pending_at >= 0 else i
                i = m.end()
                continue

            mm = NOISE_RE.match(raw, i)
            if mm:
                pending_space = True
                pending_at = pending_at if pending_at >= 0 else i
                i = mm.end()
                continue

            if ch.isspace():
                if not pending_space:
                    pending_at = i
                pending_space = True
                i += 1
                continue

            if pending_space:
                flush_space(pending_at if pending_at >= 0 else i)

            if ch in TRANSLIT:
                repl = TRANSLIT[ch]
                if repl:
                    for k, rc in enumerate(repl):
                        out.append(rc.lower())
                        origins.append(i + k if k < len(ch) else i)
            else:
                out.append(unicodedata.normalize("NFC", ch).lower())
                origins.append(i)
            i += 1

        if pending_space:
            flush_space(pending_at if pending_at >= 0 else n - 1)

        text = "".join(out).strip()
        # strip() 会挪掉前导空白，偏移表同步左移
        lead = len("".join(out)) - len(text)
        return text, origins[lead:]

    def locate(self, source_text: str) -> int:
        """引文在原始 Markdown 中的起始下标；定位不到返回 -1。"""
        start, _ = self.locate_span(source_text)
        return start

    def locate_span(self, source_text: str) -> tuple[int, int]:
        """引文覆盖的原始偏移区间 (起, 止)；定位不到返回 (-1, -1)。"""
        needle = normalize(source_text)
        if not needle:
            return -1, -1
        pos = self.norm_text.find(needle)
        if pos < 0 or pos >= len(self.norm_to_raw):
            return -1, -1
        start = self.norm_to_raw[pos]
        end = self.norm_to_raw[min(pos + len(needle) - 1, len(self.norm_to_raw) - 1)]
        return start, end + 1

    def page_of(self, source_text: str) -> tuple[int | None, bool]:
        """(页码, 是否定位成功)。定位失败时第二项 False，调用方应跳过而非判错。"""
        raw_pos = self.locate(source_text)
        if raw_pos < 0:
            return None, False
        return page_at(raw_pos, self.markers), True

    def pages_of(self, source_text: str) -> tuple[list[int], bool]:
        """引文实际触及的全部页（升序）。跨页引文会返回多页，调用方据此放宽判定。"""
        start, end = self.locate_span(source_text)
        if start < 0:
            return [], False
        pages: list[int] = []
        for i, (marker_end, num) in enumerate(self.markers):
            nxt = self.markers[i + 1][0] if i + 1 < len(self.markers) else float("inf")
            if end >= marker_end and start < nxt:
                pages.append(num)
        return pages, bool(pages)
