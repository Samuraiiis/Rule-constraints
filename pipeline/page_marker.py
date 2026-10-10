"""页码标记 ``<!-- page: N printed: M -->`` 的唯一解析入口。

N 是 PDF 物理页序号，来自 content_list_v2.json 顶层按页分组的块数组下标 + 1，恒为 1..N 单调；
M 是 OCR 从 ``page_number`` 块读到的期刊印刷页码，只作人工溯源用，禁止写进任何 page 字段。
印刷页码可能缺失（多数页没有该块）、也可能被识别成日期或卷期号，所以它不能当页码主键。

各处不要再自带 marker 正则：放宽版与旧格式 ``<!-- page: N -->`` 必须同时兼容，
漏改一处就会出现"校验器与数据同源失真"。
"""
from __future__ import annotations

import re

# 内层一律非捕获组，保证 findall / sub 拿到的是整段字符串而非元组
PAGE_MARKER_RE = re.compile(r"<!--\s*page:\s*\d+(?:\s+printed:\s*\d+)?\s*-->")
PAGE_NUM_RE = re.compile(r"<!--\s*page:\s*(\d+)(?:\s+printed:\s*(\d+))?\s*-->")


def is_page_marker(text: str) -> bool:
    return bool(PAGE_MARKER_RE.fullmatch((text or "").strip()))


def extract_pdf_page(marker_text: str) -> int:
    match = PAGE_NUM_RE.fullmatch((marker_text or "").strip())
    if not match:
        raise ValueError(f"不是合法的页码标记: {marker_text!r}")
    return int(match.group(1))


def extract_printed_page(marker_text: str) -> int | None:
    match = PAGE_NUM_RE.fullmatch((marker_text or "").strip())
    return int(match.group(2)) if match and match.group(2) else None


def pdf_page_sequence(text: str) -> list[int]:
    """按出现顺序取所有 marker 的 PDF 页序号，用于单调性断言。"""
    return [int(m.group(1)) for m in PAGE_NUM_RE.finditer(text or "")]


def strip_page_markers(text: str) -> str:
    return PAGE_MARKER_RE.sub(" ", text or "")


def split_with_markers(text: str) -> list[str]:
    """按 marker 切分并保留 marker 本身，返回 [正文, marker, 正文, marker, ...]。"""
    return re.split(f"({PAGE_MARKER_RE.pattern})", text or "")
