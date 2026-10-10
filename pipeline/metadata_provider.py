"""文献元数据读取器（实现 single_doc_runner.MetadataProvider 协议）。

职责：
    从 document_metadata.csv 惰性加载全量元数据，按 document_id 返回对应行 dict。
    元数据将传给 LLM 作为 Evidence 抽取的上下文（标题/期刊/年份/研究类型等）。

输入 / 输出：
    输入：document_id（如 BT000001）
    输出：dict（含 title/journal/year/document_type/study_type 等字段）

前置条件：
    - metadata/first/document_metadata.csv 存在且含 document_id 列

命令示例：
    python -c "
    from pathlib import Path
    from pipeline.metadata_provider import MetadataProviderImpl
    p = MetadataProviderImpl(Path('.'))
    m = p.get_metadata('BT000001')
    print(m['title'], m['journal'], m['year'])
    "
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Final

# document_metadata.csv 默认路径（相对于 project_root）
DEFAULT_METADATA_CSV: Final[str] = "metadata/first/document_metadata.csv"


class MetadataProviderImpl:
    """文献元数据读取器，实现 MetadataProvider Protocol。

    构造参数：
        project_root     项目根目录
        csv_path          document_metadata.csv 路径（默认 project_root / metadata/first/）
    """

    def __init__(
        self,
        project_root: Path,
        csv_path: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.csv_path = (
            csv_path
            or (self.project_root / DEFAULT_METADATA_CSV)
        ).resolve()
        self._cache: dict[str, dict[str, str]] | None = None  # 惰性加载

    def _load(self) -> dict[str, dict[str, str]]:
        """惰性加载 CSV，返回 {document_id: {col: val}} 映射。"""
        if self._cache is not None:
            return self._cache

        if not self.csv_path.exists():
            raise FileNotFoundError(f"document_metadata.csv 不存在: {self.csv_path}")

        cache: dict[str, dict[str, str]] = {}
        with open(self.csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if "document_id" not in (reader.fieldnames or []):
                raise ValueError(
                    f"document_metadata.csv 缺少 document_id 列，"
                    f"实际列: {reader.fieldnames}"
                )
            for row in reader:
                doc_id = row["document_id"].strip()
                if doc_id:
                    cache[doc_id] = {k: (v.strip() if v else "") for k, v in row.items()}

        self._cache = cache
        return cache

    def get_metadata(self, document_id: str) -> dict[str, Any]:
        """返回该文献的元数据 dict。

        异常：
            KeyError  document_id 不在 CSV 中
        """
        cache = self._load()
        if document_id not in cache:
            raise KeyError(
                f"document_id '{document_id}' 不在 document_metadata.csv 中"
                f"（共 {len(cache)} 条记录）"
            )
        return dict(cache[document_id])


# --------------------------------------------------------------------------- #
# 命令行自检
# --------------------------------------------------------------------------- #
def _main() -> int:
    """命令行自检。

    用法：
        python -m pipeline.metadata_provider <document_id> [project_root]
    """
    if len(sys.argv) < 2:
        print("用法: python -m pipeline.metadata_provider <document_id> [project_root]")
        return 2

    doc_id = sys.argv[1]
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
    provider = MetadataProviderImpl(root)

    try:
        meta = provider.get_metadata(doc_id)
    except (KeyError, FileNotFoundError) as exc:
        print(f"读取失败: {exc}")
        return 1

    print(f"document_id : {doc_id}")
    print(f"title       : {meta.get('title', '')}")
    print(f"journal     : {meta.get('journal', '')}")
    print(f"year        : {meta.get('year', '')}")
    print(f"doc_type    : {meta.get('document_type', '')}")
    print(f"study_type  : {meta.get('study_type', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
