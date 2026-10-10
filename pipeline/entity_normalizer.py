"""Entity 词典标准化器（实现 single_doc_runner.EntityNormalizer 协议）。

Schema_rules §8 / Entity_schema §9：
    "LLM 负责发现实体，词典/本体负责标准化。"

从 dictionaries/ 目录加载 6 个标准词典 CSV，按 entity_type 查找对应词典，
mention 精确/忽略大小写匹配 → 填充 canonical_name + ontology_id。
无匹配或 entity_type 不在词典覆盖范围 → canonical_name=null, ontology_id=null。

匹配策略（Schema_rules §8 "仅允许已确认的同义词映射"）：
    1. 精确匹配（mention == synonym）
    2. 忽略大小写匹配（mention.lower() == synonym.lower()）
    不做模糊匹配 / 编辑距离匹配——避免误合并。

词典 CSV 格式（由 scripts/build_dictionaries.py 生成）：
    canonical_name, synonym, entity_type, ontology_id, source
    synonym 字段为分号分隔的同义 mention 列表

命令示例：
    # 单篇标准化测试
    python -m pipeline.entity_normalizer BT000001

前置条件：
    - dictionaries/ 目录下有词典 CSV（由 scripts/build_dictionaries.py 生成）
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Final

from pipeline.single_doc_runner import EntityNormalizer

# --------------------------------------------------------------------------- #
# 词典映射（与 scripts/build_dictionaries.py 保持一致）
# --------------------------------------------------------------------------- #
DICT_MAPPING: Final[dict[str, list[str]]] = {
    "disease_dictionary": ["Disease"],
    "anatomy_dictionary": ["Anatomy"],
    "mri_sequence_dictionary": ["MRISequence", "ImagingModality", "ContrastAgent"],
    "imaging_finding_dictionary": ["ImagingFinding"],
    "treatment_dictionary": ["Treatment"],
    "biomarker_dictionary": ["Biomarker", "MolecularFeature", "GeneticFeature"],
}

# 反向映射：entity_type → dict_name
_ENTITY_TO_DICT: dict[str, str] = {}
for _dn, _etypes in DICT_MAPPING.items():
    for _et in _etypes:
        _ENTITY_TO_DICT[_et] = _dn


class EntityNormalizerImpl:
    """Entity 词典标准化器，实现 EntityNormalizer Protocol。

    构造参数：
        project_root  项目根目录（dictionaries/ 的父目录）
    """

    def __init__(self, project_root: Path | None = None) -> None:
        root = project_root or Path(__file__).resolve().parent.parent
        self._dict_dir: Path = root / "dictionaries"
        # 词典索引：(entity_type, mention_lower) → (canonical_name, ontology_id)
        self._index: dict[tuple[str, str], tuple[str | None, str | None]] = {}
        # 已加载的词典文件集合（用于状态报告）
        self._loaded_dicts: set[str] = set()
        self._loaded = False

    # -- 词典加载 ----------------------------------------------------------- #
    def _load_all(self) -> None:
        """加载所有词典 CSV 到内存索引（惰性加载，仅一次）。"""
        if self._loaded:
            return

        for dict_name in DICT_MAPPING:
            csv_path = self._dict_dir / f"{dict_name}.csv"
            if not csv_path.exists():
                continue

            try:
                self._load_csv(csv_path)
                self._loaded_dicts.add(dict_name)
            except (OSError, csv.Error) as exc:
                print(f"  警告: 加载词典 {csv_path.name} 失败: {exc}")

        self._loaded = True

    def _load_csv(self, csv_path: Path) -> int:
        """加载单个词典 CSV，构建索引。

        返回加载的条目数。
        """
        count = 0
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                canonical = (row.get("canonical_name") or "").strip()
                synonyms_str = row.get("synonym") or ""
                etype = (row.get("entity_type") or "").strip()
                ontology_id = (row.get("ontology_id") or "").strip() or None

                if not canonical or not etype:
                    continue

                # synonym 字段为分号分隔的列表
                synonyms = [s.strip() for s in synonyms_str.split(";") if s.strip()]
                # canonical_name 本身也作为可匹配的 mention
                if canonical not in synonyms:
                    synonyms.append(canonical)

                for syn in synonyms:
                    key = (etype, syn.lower())
                    # 首次写入优先；后续重复同义词条目不覆盖
                    if key not in self._index:
                        self._index[key] = (canonical, ontology_id or None)
                    count += 1

        return count

    # -- 标准化 ------------------------------------------------------------- #
    def normalize(self, entity: dict[str, Any], document_id: str) -> dict[str, Any]:
        """对单个 Entity 填充 canonical_name / ontology_id。

        匹配策略：
            1. 精确匹配（mention == synonym）
            2. 忽略大小写匹配
            无匹配 → canonical_name=null, ontology_id=null

        参数：
            entity      Entity dict（含 entity_type, mention 等字段）
            document_id 文献 ID（当前未用于匹配，保留接口）
        返回：
            补全 canonical_name / ontology_id 的 entity（原 dict 被修改）
        """
        self._load_all()

        etype = entity.get("entity_type", "")
        mention = entity.get("mention", "")

        # entity_type 不在词典覆盖范围 → 直接置 null
        if etype not in _ENTITY_TO_DICT:
            entity["canonical_name"] = None
            entity["ontology_id"] = None
            return entity

        # 精确匹配（大小写敏感）
        key_exact = (etype, mention)
        # 忽略大小写匹配
        key_lower = (etype, mention.lower())

        # 先查精确，再查忽略大小写
        # 索引本身以 lower 存储，所以直接用 lower 查
        result = self._index.get(key_lower)
        if result:
            entity["canonical_name"] = result[0]
            entity["ontology_id"] = result[1]
        else:
            entity["canonical_name"] = None
            entity["ontology_id"] = None

        return entity

    # -- 状态报告 ----------------------------------------------------------- #
    def status(self) -> str:
        """返回词典加载状态摘要（用于日志/自检）。"""
        self._load_all()
        lines = [
            f"词典目录: {self._dict_dir}",
            f"已加载词典: {len(self._loaded_dicts)} / {len(DICT_MAPPING)}",
        ]
        for dn in DICT_MAPPING:
            status = "✓" if dn in self._loaded_dicts else "✗"
            lines.append(f"  {status} {dn}")
        lines.append(f"索引条目数: {len(self._index)}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 命令行入口
# --------------------------------------------------------------------------- #
def _main() -> int:
    """命令行入口：单篇 Entity 标准化测试。

    用法：
        python -m pipeline.entity_normalizer BT000001
    """
    if len(sys.argv) < 2:
        print("用法: python -m pipeline.entity_normalizer <document_id>")
        return 2

    doc_id = sys.argv[1]
    project_root = Path(__file__).resolve().parent.parent

    # 读取 Entity 缓存
    from pipeline.cache_manager import get_cache_path
    import json

    entity_cache_path = get_cache_path(doc_id, "entity", project_root)
    if not entity_cache_path.exists():
        print(f"未找到 Entity 缓存: {entity_cache_path}")
        return 1

    cache = json.loads(entity_cache_path.read_text(encoding="utf-8"))
    entities = cache.get("entities", [])
    metadata = cache.get("metadata", {})

    print(f"Entity 缓存: {entity_cache_path}")
    print(f"标题      : {metadata.get('title', '')[:60]}")
    print(f"Entity 数量: {len(entities)}")

    # 初始化 normalizer
    normalizer = EntityNormalizerImpl(project_root)
    print(f"\n{normalizer.status()}")

    # 标准化
    print(f"\n开始标准化 document_id={doc_id} 的 Entity...\n")
    print("=" * 80)
    for i, ent in enumerate(entities):
        etype = ent.get("entity_type", "?")
        mention = ent.get("mention", "?")

        normalized = normalizer.normalize(dict(ent), doc_id)
        canonical = normalized.get("canonical_name")
        ontology = normalized.get("ontology_id")

        matched = canonical is not None
        status = "✓ 匹配" if matched else "✗ 无匹配"
        print(f"[{i+1}] {etype:20s} | mention: {mention}")
        print(f"     {status}")
        print(f"     canonical_name: {canonical}")
        print(f"     ontology_id   : {ontology}")
        print("-" * 80)

    # 统计
    matched_count = sum(
        1 for ent in entities
        if normalizer.normalize(dict(ent), doc_id).get("canonical_name") is not None
    )
    print(f"\n匹配: {matched_count} / {len(entities)}")
    print(f"未匹配: {len(entities) - matched_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
