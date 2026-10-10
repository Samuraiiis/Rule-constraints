"""OCR Markdown 读取器（实现 single_doc_runner.MarkdownReader 协议）。

职责：
    1. 从 file_index.csv 加载 document_id → markdown_path 映射
    2. 读取 .md 文件原文
    3. 可选：从 content_list_v2.json 注入 ``<!-- page: N -->`` 页码标记

页码注入策略：
    content_list_v2.json 外层数组 = 页面列表，每页含 text/title/table 等块，
    以及 ``page_number`` 块（内容如 "275"）。本模块从中重建带页码标记的
    Markdown 文本；若重建文本长度 < .md 原文的 50%，回退到 .md 原文（page 将为 null）。

    这符合 Evidence_schema §9："如果 Markdown 无法可靠映射 PDF 页码，可为 null"。

输入 / 输出：
    输入：document_id（如 BT000001）
    输出：(markdown_text, md_file_path) —— 带页码标记的 Markdown 文本 + .md 绝对路径

前置条件：
    - metadata/first/file_index.csv 存在且含 markdown_path 列
    - .md 文件存在于 file_index.csv 指定的相对路径

命令示例：
    python -c "
    from pathlib import Path
    from pipeline.markdown_reader import MarkdownReaderImpl
    r = MarkdownReaderImpl(Path('.'))
    text, path = r.read('BT000001')
    print(f'读取 {path.name}，{len(text)} 字符')
    print(text[:200])
    "
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Final

# file_index.csv 默认路径（相对于 project_root）
DEFAULT_FILE_INDEX: Final[str] = "metadata/first/file_index.csv"

# content_list_v2.json 文件名后缀
CONTENT_LIST_V2_SUFFIX: Final[str] = "_content_list_v2.json"

# 重建文本最小比例（低于此值则回退到 .md 原文）
MIN_RECONSTRUCT_RATIO: Final[float] = 0.5


class MarkdownReaderImpl:
    """OCR Markdown 读取器，实现 MarkdownReader Protocol。

    构造参数：
        project_root     项目根目录（.md 路径以此为基准解析）
        file_index_path  file_index.csv 路径（默认 project_root / metadata/first/file_index.csv）
    """

    def __init__(
        self,
        project_root: Path,
        file_index_path: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.file_index_path = (
            file_index_path
            or (self.project_root / DEFAULT_FILE_INDEX)
        ).resolve()
        # document_id → markdown_path（相对路径字符串）
        self._index: dict[str, str] | None = None  # 惰性加载

    # -- file_index 加载 ---------------------------------------------------- #
    def _load_index(self) -> dict[str, str]:
        """惰性加载 file_index.csv，返回 {document_id: markdown_path} 映射。"""
        if self._index is not None:
            return self._index

        if not self.file_index_path.exists():
            raise FileNotFoundError(
                f"file_index.csv 不存在: {self.file_index_path}"
            )

        index: dict[str, str] = {}
        with open(self.file_index_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fns = reader.fieldnames or []
            if "document_id" not in fns or "markdown_path" not in fns:
                raise ValueError(
                    f"file_index.csv 缺少 document_id 或 markdown_path 列，"
                    f"实际列: {reader.fieldnames}"
                )
            for row in reader:
                doc_id = row["document_id"].strip()
                md_path = row["markdown_path"].strip()
                if doc_id and md_path:
                    index[doc_id] = md_path

        self._index = index
        return index

    # -- 公开接口 ----------------------------------------------------------- #
    def read(self, document_id: str) -> tuple[str, Path]:
        """返回 (markdown 文本, .md 文件绝对路径)。

        流程：
            1. 查 file_index → markdown_path（相对 project_root）
            2. 读取 .md 原文
            3. 尝试从 content_list_v2.json 注入页码标记
            4. 回退：若页码注入失败或重建文本过短，使用 .md 原文
        """
        index = self._load_index()
        if document_id not in index:
            raise FileNotFoundError(
                f"document_id '{document_id}' 不在 file_index.csv 中"
                f"（共 {len(index)} 条记录）"
            )

        # 解析 .md 绝对路径
        md_rel = index[document_id]
        md_path = (self.project_root / md_rel).resolve()
        if not md_path.exists():
            raise FileNotFoundError(f".md 文件不存在: {md_path}")

        # 读取 .md 原文
        md_text = md_path.read_text(encoding="utf-8")

        # 尝试页码注入
        content_list_path = self._find_content_list_v2(md_path)
        if content_list_path is not None:
            annotated = self._build_page_annotated_markdown(content_list_path)
            if annotated and len(annotated) >= len(md_text) * MIN_RECONSTRUCT_RATIO:
                return annotated, md_path

        # 回退：使用 .md 原文（无页码标记）
        return md_text, md_path

    # -- content_list_v2.json 定位 ----------------------------------------- #
    def _find_content_list_v2(self, md_path: Path) -> Path | None:
        """从 .md 路径推断 content_list_v2.json 路径。

        MinerU 输出规则：同目录下，{pdf_stem}_content_list_v2.json
        """
        stem = md_path.stem  # 如 "02-NO5.2-Meyers"
        candidate = md_path.parent / f"{stem}{CONTENT_LIST_V2_SUFFIX}"
        return candidate if candidate.exists() else None

    # -- 页码标记注入 ------------------------------------------------------- #
    def _build_page_annotated_markdown(self, content_list_path: Path) -> str | None:
        """从 content_list_v2.json 重建带 ``<!-- page: N -->`` 标记的 Markdown。

        返回 None 表示解析失败（调用方回退到 .md 原文）。
        """
        try:
            data = json.loads(content_list_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        if not isinstance(data, list) or not data:
            return None

        lines: list[str] = []
        for page_idx, page_blocks in enumerate(data):
            if not isinstance(page_blocks, list):
                continue

            # 页码标记：固定 1..N 单调递增（PDF 物理页序号），保证下游校验器
            # 能做单调性断言。期刊印刷页码（page_number 块的值）另存为
            # sidecar 属性 printed，不污染 page 标记本身。
            # 旧实现把 page_number 块的值直接写进 marker，导致 BT000274 出现
            # [823, 2, 3, 826, 5, 6] 这种混排，Agent 逐字引用后 page 字段脏，
            # check_agent_raw 又拿同一份输入回比，page 校验 0 error 但实际全错。
            pdf_page = page_idx + 1
            printed = self._extract_printed_page_number(page_blocks)
            if printed is not None:
                lines.append(f"<!-- page: {pdf_page} printed: {printed} -->")
            else:
                lines.append(f"<!-- page: {pdf_page} -->")
            lines.append("")

            # 提取文本块
            for block in page_blocks:
                text = self._extract_block_text(block)
                if text:
                    lines.append(text)
                    lines.append("")

        return "\n".join(lines) if lines else None

    def _extract_printed_page_number(
        self,
        page_blocks: list[dict[str, Any]],
    ) -> int | None:
        """从页面块中提取 page_number 块的印刷页码（期刊印刷页码）；无则返回 None。

        与 _extract_page_number 旧实现不同：本方法只用于 sidecar 属性 printed，
        不影响 page 标记本身（page 标记固定 1..N）。
        """
        for block in page_blocks:
            if block.get("type") == "page_number":
                content = block.get("content", {})
                parts = content.get("page_number_content", [])
                for part in parts:
                    raw = str(part.get("content", "")).strip()
                    if raw.isdigit():
                        return int(raw)
        return None

    def _extract_block_text(self, block: dict[str, Any]) -> str:
        """从 content_list_v2.json 的单个块提取文本，转为 Markdown。

        支持类型：title（按 level 加 ##）、paragraph、image（图注）、table（表格+caption）。
        忽略：page_header、page_number、page_footer（非正文内容）。
        """
        btype = block.get("type", "")
        content = block.get("content", {})

        if btype == "title":
            return self._extract_title(content)

        if btype == "paragraph":
            return self._extract_paragraph(content)

        if btype == "equation_interline":
            return self._extract_equation_interline(content)

        if btype == "image":
            return self._extract_image(content)

        if btype == "table":
            return self._extract_table(content)

        # page_header / page_number / page_footer / 其他 → 跳过
        return ""

    def _extract_title(self, content: dict[str, Any]) -> str:
        """提取标题块，按 level 转为 Markdown 标题。"""
        parts = content.get("title_content", [])
        text = self._join_text_parts(parts)
        if not text:
            return ""
        level = content.get("level", 1)
        level = max(1, min(level, 6))  # Markdown 最多 6 级
        return f"{'#' * level} {text}"

    def _extract_paragraph(self, content: dict[str, Any]) -> str:
        """提取段落块文本。"""
        parts = content.get("paragraph_content", [])
        return self._join_text_parts(parts)

    def _extract_equation_interline(self, content: dict[str, Any]) -> str:
        """独立公式块 → $$..$$（与 MinerU .md 约定一致）。

        content 形如 {"math_content": "S = ..", "math_type": "latex", ...}。
        """
        math = str(content.get("math_content", "") or "").strip()
        return f"$$\n{math}\n$$" if math else ""

    def _extract_image(self, content: dict[str, Any]) -> str:
        """提取图片块：输出图片引用 + 图注（若有）。"""
        img_path = content.get("img_path", "")
        caption_parts = content.get("img_caption", [])
        caption = self._join_text_parts(
            [p for p in caption_parts if isinstance(p, dict)]
        )
        ref = f"![](images/{Path(img_path).name})" if img_path else "![](images/)"
        if caption:
            return f"{ref}\n\n*{caption}*"
        return ref

    def _extract_table(self, content: dict[str, Any]) -> str:
        """提取表格块：输出表格体 + caption（若有）。"""
        body = content.get("table_body", "")
        caption_parts = content.get("table_caption", [])
        caption = self._join_text_parts(
            [p for p in caption_parts if isinstance(p, dict)]
        )
        parts: list[str] = []
        if caption:
            parts.append(f"**{caption}**\n")
        if body:
            parts.append(str(body))
        return "\n".join(parts) if parts else ""

    def _join_text_parts(self, parts: list[Any]) -> str:
        """从 part 列表拼接纯文本。

        part 形如 {"type":"text","content":"..."} 或
        {"type":"equation_inline","content":"\\rho"}。

        equation_inline（内联公式）必须保留：希腊字母/上下标常存这里
        （ρ 写作 \\rho、上标写作 ^{a}）。旧实现只保留 text part，公式被静默
        丢弃 → "pseudo ρ-map" 重建成 "pseudo      map"（空白 run），
        实体无法整词命中、词典无法归一（EXTRACTION_SPEC §9 行 15）。
        现按 MinerU .md 的约定渲染为 $...$（.md 原文即 "quantitative $\\rho$ -mapping"）。
        """
        texts: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            c = part.get("content", "")
            if not c:
                continue
            if ptype == "text":
                texts.append(str(c))
            elif ptype == "equation_inline":
                texts.append(f"${str(c).strip()}$")
        return " ".join(texts).strip()


# --------------------------------------------------------------------------- #
# 命令行自检
# --------------------------------------------------------------------------- #
def _main() -> int:
    """命令行自检：验证 MarkdownReader 能读取真实 .md 文件。

    用法：
        python -m pipeline.markdown_reader <document_id> [project_root]
    """
    if len(sys.argv) < 2:
        print("用法: python -m pipeline.markdown_reader <document_id> [project_root]")
        return 2

    doc_id = sys.argv[1]
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
    reader = MarkdownReaderImpl(root)

    try:
        text, md_path = reader.read(doc_id)
    except FileNotFoundError as exc:
        print(f"读取失败: {exc}")
        return 1

    # 统计页码标记
    page_markers = text.count("<!-- page:")
    print(f"document_id  : {doc_id}")
    print(f"md_path      : {md_path}")
    print(f"文本长度     : {len(text)} 字符")
    print(f"页码标记数   : {page_markers}")
    print(f"前 200 字符  : {text[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
