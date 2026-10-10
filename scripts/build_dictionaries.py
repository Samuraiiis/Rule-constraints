"""从已抽取 Entity 数据构建 6 类标准词典草案（Schema_rules §8）。

扫描 data/extracted/{RUN_VERSION}/*_entity.json，按 entity_type 分组收集
mention 变体，调用 LLM 保守地分组同义词并生成 canonical_name 草案，
最终保存 6 个 CSV 词典到 dictionaries/ 目录。

词典映射（Schema_rules §8 指定的 6 个标准词典）：
    disease_dictionary.csv         → Disease
    anatomy_dictionary.csv         → Anatomy
    mri_sequence_dictionary.csv     → MRISequence, ImagingModality, ContrastAgent
    imaging_finding_dictionary.csv  → ImagingFinding
    treatment_dictionary.csv       → Treatment
    biomarker_dictionary.csv       → Biomarker, MolecularFeature, GeneticFeature

未被任何词典覆盖的 entity_type（Pathology, ClinicalFeature, Symptom,
RiskFactor, Complication, StudyPopulation, Other）不生成词典，
canonical_name 保持 null。

CSV 字段（Schema_rules §8 建议字段 + source）：
    canonical_name, synonym, entity_type, ontology_id, source

    synonym  —— 分号分隔的同义 mention 列表
    source   —— 分号分隔的来源 document_id 列表

核心约束（Schema_rules §8 / §22）：
    "不得仅依据模型知识自动视为同义词。"
    LLM 仅允许分组：大小写差异、缩写与全称（两者都在 mention 列表中出现时）、
    单复数、明显 OCR 错误。不得凭医学常识将 "high-grade glioma" 与
    "glioblastoma" 合并。

缓存：
    LLM 原始响应保存到 dictionaries/.cache/{dict_name}_draft.json
    再次运行直接读缓存不调 LLM；--force 强制重新调用。

命令示例：
    python -m scripts.build_dictionaries            # 构建全部词典
    python -m scripts.build_dictionaries --force    # 强制重新抽取
    python -m scripts.build_dictionaries --list      # 列出可用 Entity 数据
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Final

# 项目根目录（scripts/ 的父目录）
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# 词典输出目录
_DICT_DIR: Path = _PROJECT_ROOT / "dictionaries"

# LLM 缓存目录
_CACHE_DIR: Path = _DICT_DIR / ".cache"

# --------------------------------------------------------------------------- #
# 词典映射（Schema_rules §8 指定的 6 个标准词典）
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

# 不在词典覆盖范围内的 entity_type
NO_DICT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "Pathology",
        "ClinicalFeature",
        "Symptom",
        "RiskFactor",
        "Complication",
        "StudyPopulation",
        "Other",
    }
)

# CSV 表头
CSV_HEADER: Final[tuple[str, ...]] = (
    "canonical_name",
    "synonym",
    "entity_type",
    "ontology_id",
    "source",
)


# --------------------------------------------------------------------------- #
# 数据扫描
# --------------------------------------------------------------------------- #
def scan_entity_files(extract_dir: Path) -> list[Path]:
    """扫描提取结果目录下的所有 *_entity.json 文件。

    参数：
        extract_dir  data/extracted/{RUN_VERSION}/ 目录
    返回：
        按文件名排序的 Path 列表
    """
    if not extract_dir.exists():
        return []
    return sorted(extract_dir.glob("*_entity.json"))


def collect_mentions(
    entity_files: list[Path],
) -> dict[str, dict[str, dict[str, set[str]]]]:
    """从 Entity 缓存文件收集 mention，按 词典→entity_type→mention→doc_ids 分组。

    返回结构：
        {
            "disease_dictionary": {
                "Disease": {
                    "glioblastoma": {"BT000001", "BT000002"},
                    "GBM": {"BT000001"},
                }
            },
            ...
        }

    参数：
        entity_files  Entity 缓存文件路径列表
    """
    result: dict[str, dict[str, dict[str, set[str]]]] = {
        dn: {} for dn in DICT_MAPPING
    }

    for fpath in entity_files:
        try:
            cache = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  警告: 跳过无法解析的文件 {fpath.name}: {exc}")
            continue

        doc_id = cache.get("document_id", fpath.stem.replace("_entity", ""))
        entities = cache.get("entities", [])

        for ent in entities:
            etype = ent.get("entity_type", "")
            mention = ent.get("mention", "")

            if not etype or not mention:
                continue

            dict_name = _ENTITY_TO_DICT.get(etype)
            if dict_name is None:
                # 不在词典覆盖范围内的类型，跳过
                continue

            if etype not in result[dict_name]:
                result[dict_name][etype] = {}

            if mention not in result[dict_name][etype]:
                result[dict_name][etype][mention] = set()

            result[dict_name][etype][mention].add(doc_id)

    return result


# --------------------------------------------------------------------------- #
# LLM Prompt 构建
# --------------------------------------------------------------------------- #
def build_system_prompt() -> str:
    """构建 system prompt（静态）。

    核心原则：仅分组明确同义的 mention，不得凭医学常识合并概念相关但
    非严格等价的术语。
    """
    return """你是一名脑部 MRI 医学文献词典构建助手。你的任务是将从文献中抽取的
mention（原文表述）分组，为每组生成 canonical_name（标准名称）和 synonym 列表。

## 核心原则（不可违背）
1. **仅分组明确同义的 mention**——以下情况可以合并：
   - 大小写差异（如 "GBM" 与 "gbm"）
   - 缩写与全称（如 "GBM" 与 "Glioblastoma"，仅当两者都在 mention 列表中出现时）
   - 单复数差异（如 "metastasis" 与 "metastases"）
   - 明显的 OCR 错误或拼写变体（如 "gllioblastoma" 与 "glioblastoma"）

2. **不得凭医学常识合并概念相关但非严格等价的术语**——以下情况不得合并：
   - "high-grade glioma" 与 "glioblastoma"（二者并非严格等价）
   - "stroke" 与 "ischemic stroke"（范围不同）
   - "T2" 与 "T2-FLAIR"（不同序列）

3. **canonical_name 选择规则**：
   - 优先选择全称而非缩写（如 "Glioblastoma" 而非 "GBM"）
   - 优先选择学术标准表述
   - 如果无法确定标准名称，使用 mention 列表中最长的表述
   - canonical_name 必须来自 mention 列表中的某个变体，不得自行编造

4. **ontology_id 始终为 null**——草案阶段不做本体映射。

## 输出格式
返回一个 JSON 对象：
```json
{
  "groups": [
    {
      "canonical_name": "Glioblastoma",
      "synonyms": ["Glioblastoma", "GBM", "glioblastoma"],
      "entity_type": "Disease",
      "ontology_id": null,
      "note": "缩写 GBM 与全称 Glioblastoma 合并"
    }
  ]
}
```

每个 mention 必须出现在且仅出现在一个 group 的 synonyms 中。
如果某个 mention 无法与任何其他 mention 合并，它自成一组：
synonyms 只含它自身，canonical_name 等于它自身，note 为空字符串。
"""


def build_user_prompt(
    dict_name: str,
    mentions_by_type: dict[str, dict[str, set[str]]],
) -> str:
    """构建 user prompt（动态，含 mention 列表 + 来源）。

    参数：
        dict_name         词典名称（如 "disease_dictionary"）
        mentions_by_type  该词典下的 {entity_type: {mention: {doc_ids}}} 数据
    """
    lines: list[str] = []
    lines.append(f"## 词典：{dict_name}")
    lines.append("")

    for etype, mentions in sorted(mentions_by_type.items()):
        lines.append(f"### entity_type: {etype}")
        lines.append("")

        # 列出所有 mention 及其来源文档
        for i, (mention, doc_ids) in enumerate(sorted(mentions.items()), 1):
            sources = ";".join(sorted(doc_ids))
            lines.append(f"{i}. mention: \"{mention}\"  (来源: {sources})")

        lines.append("")

    lines.append("---")
    lines.append("请按照系统指令将上述 mention 分组，返回 JSON 对象。")
    lines.append("每个 mention 必须出现在且仅出现在一个 group 的 synonyms 中。")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# LLM 调用 + 解析
# --------------------------------------------------------------------------- #
def call_llm_for_dict(
    dict_name: str,
    mentions_by_type: dict[str, dict[str, set[str]]],
    llm_client: Any,
) -> list[dict[str, Any]]:
    """调用 LLM 为一个词典生成分组草案。

    参数：
        dict_name         词典名称
        mentions_by_type  该词典下的 mention 数据
        llm_client        LLMClient 实例
    返回：
        词典条目列表（每条含 canonical_name, synonyms, entity_type, ontology_id, source, note）
    """
    from pipeline.llm_client import LLMError

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(dict_name, mentions_by_type)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    max_retries = 3
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            raw = llm_client.chat_json(messages)
        except LLMError as exc:
            last_error = str(exc)
            if attempt < max_retries:
                print(f"    LLM 调用失败（attempt {attempt}）: {exc}，重试中...")
                continue
            raise

        # 解析 JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = f"INVALID_JSON: {exc.msg}"
            if attempt < max_retries:
                print(f"    JSON 解析失败（attempt {attempt}）: {exc}，重试中...")
                # 重试时追加纠正提示
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"上次的输出不是合法 JSON: {exc.msg}\n"
                            "请重新输出合法的 JSON 对象（包含 \"groups\" 数组）。"
                        ),
                    }
                )
                continue
            raise ValueError(f"LLM 返回非合法 JSON，重试 {max_retries} 次后仍失败: {last_error}") from exc

        # 校验结构
        if not isinstance(data, dict) or "groups" not in data:
            last_error = "INVALID_STRUCTURE: 缺少 'groups' 数组"
            if attempt < max_retries:
                print(f"    结构校验失败（attempt {attempt}）: 缺少 groups，重试中...")
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "上次的输出缺少 'groups' 数组。"
                            "请重新输出 JSON 对象，格式为 {\"groups\": [...]}."
                        ),
                    }
                )
                continue
            raise ValueError(f"LLM 返回结构异常: {last_error}")

        groups = data["groups"]
        if not isinstance(groups, list):
            raise ValueError("LLM 返回的 'groups' 不是数组")

        # 解析成功
        return _validate_and_enrich_groups(groups, mentions_by_type)

    raise ValueError(f"LLM 调用失败，重试 {max_retries} 次后仍失败: {last_error}")


def _validate_and_enrich_groups(
    groups: list[dict[str, Any]],
    mentions_by_type: dict[str, dict[str, set[str]]],
) -> list[dict[str, Any]]:
    """校验 LLM 输出的分组，并补充 source 字段。

    校验项：
        1. 每条含 canonical_name, synonyms, entity_type
        2. canonical_name 非空
        3. synonyms 非空数组
        4. entity_type 在 mentions_by_type 的键中
        5. 所有 mention 都被分配到某个 group

    补充：
        - source: 从 mentions_by_type 查找每个 synonym 的来源 doc_ids
    """
    # 构建 mention → doc_ids 的反向索引
    mention_to_docs: dict[str, dict[str, set[str]]] = {}
    for etype, mentions in mentions_by_type.items():
        for mention, doc_ids in mentions.items():
            if mention not in mention_to_docs:
                mention_to_docs[mention] = {}
            mention_to_docs[mention][etype] = doc_ids

    # 记录已分配的 mention
    assigned_mentions: set[str] = set()
    entries: list[dict[str, Any]] = []

    for i, group in enumerate(groups):
        canonical = group.get("canonical_name", "")
        synonyms = group.get("synonyms", [])
        etype = group.get("entity_type", "")
        note = group.get("note", "")

        if not canonical or not str(canonical).strip():
            print(f"    警告: groups[{i}] canonical_name 为空，跳过")
            continue

        if not isinstance(synonyms, list) or not synonyms:
            print(f"    警告: groups[{i}] synonyms 为空，跳过")
            continue

        if etype not in mentions_by_type:
            print(f"    警告: groups[{i}] entity_type='{etype}' 不在预期中，跳过")
            continue

        # 收集 source
        source_docs: set[str] = set()
        for syn in synonyms:
            syn_str = str(syn)
            assigned_mentions.add(syn_str)
            docs_map = mention_to_docs.get(syn_str)
            if docs_map and etype in docs_map:
                source_docs.update(docs_map[etype])

        entries.append(
            {
                "canonical_name": canonical,
                "synonyms": [str(s) for s in synonyms],
                "entity_type": etype,
                "ontology_id": group.get("ontology_id"),
                "source": sorted(source_docs),
                "note": note,
            }
        )

    # 检查是否有未被分配的 mention
    all_mentions = set()
    for mentions in mentions_by_type.values():
        all_mentions.update(mentions.keys())

    unassigned = all_mentions - assigned_mentions
    if unassigned:
        print(f"    警告: {len(unassigned)} 个 mention 未被 LLM 分配，自动补为独立条目")
        for mention in sorted(unassigned):
            # 查找该 mention 的 entity_type 和 source
            for etype, mentions in mentions_by_type.items():
                if mention in mentions:
                    entries.append(
                        {
                            "canonical_name": mention,
                            "synonyms": [mention],
                            "entity_type": etype,
                            "ontology_id": None,
                            "source": sorted(mentions[mention]),
                            "note": "自动补充：LLM 未分配",
                        }
                    )
                    break

    return entries


# --------------------------------------------------------------------------- #
# 缓存读写
# --------------------------------------------------------------------------- #
def get_cache_path(dict_name: str) -> Path:
    """获取词典 LLM 响应的缓存路径。"""
    return _CACHE_DIR / f"{dict_name}_draft.json"


def load_cache(dict_name: str) -> list[dict[str, Any]] | None:
    """读取词典缓存。返回 entries 列表或 None。"""
    cache_path = get_cache_path(dict_name)
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data.get("entries")
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(
    dict_name: str,
    entries: list[dict[str, Any]],
    model: str,
    mentions_count: int,
) -> Path:
    """保存词典 LLM 响应到缓存。"""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = get_cache_path(dict_name)
    cache_data = {
        "dict_name": dict_name,
        "model": model,
        "mentions_count": mentions_count,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entries": entries,
    }
    cache_path.write_text(
        json.dumps(cache_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cache_path


# --------------------------------------------------------------------------- #
# CSV 输出
# --------------------------------------------------------------------------- #
def save_dictionary_csv(dict_name: str, entries: list[dict[str, Any]]) -> Path:
    """将词典条目保存为 CSV 文件。

    CSV 格式：canonical_name, synonym, entity_type, ontology_id, source
    """
    _DICT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = _DICT_DIR / f"{dict_name}.csv"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

        for entry in entries:
            synonyms_str = ";".join(entry["synonyms"])
            source_str = ";".join(entry["source"])
            ontology_id = entry.get("ontology_id") or ""
            writer.writerow(
                [
                    entry["canonical_name"],
                    synonyms_str,
                    entry["entity_type"],
                    ontology_id,
                    source_str,
                ]
            )

    return csv_path


# --------------------------------------------------------------------------- #
# 命令行入口
# --------------------------------------------------------------------------- #
def _list_entity_data() -> int:
    """列出可用的 Entity 数据文件。"""
    from pipeline.cache_manager import get_extract_dir

    extract_dir = get_extract_dir(_PROJECT_ROOT)
    entity_files = scan_entity_files(extract_dir)

    if not entity_files:
        print(f"未找到 Entity 数据文件: {extract_dir}")
        print("请先运行 Entity 抽取: python -m pipeline.entity_extractor <doc_id>")
        return 1

    print(f"Entity 数据目录: {extract_dir}")
    print(f"文件数量: {len(entity_files)}")
    print("=" * 80)

    # 统计 entity_type 分布
    type_counts: dict[str, int] = {}
    total_entities = 0

    for fpath in entity_files:
        try:
            cache = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        doc_id = cache.get("document_id", "?")
        entities = cache.get("entities", [])
        total_entities += len(entities)

        for ent in entities:
            etype = ent.get("entity_type", "?")
            type_counts[etype] = type_counts.get(etype, 0) + 1

        print(f"  {doc_id:12s} | {len(entities):3d} entities | {fpath.name}")

    print("=" * 80)
    print(f"总 Entity 数量: {total_entities}")
    print("\n按 entity_type 统计:")
    for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        dict_name = _ENTITY_TO_DICT.get(etype, "(无词典)")
        print(f"  {etype:20s}: {count:4d}  → {dict_name}")

    # 词典覆盖统计
    print("\n词典覆盖:")
    for dn, etypes in DICT_MAPPING.items():
        covered = sum(type_counts.get(et, 0) for et in etypes)
        print(f"  {dn:35s}: {covered:4d}  (类型: {', '.join(etypes)})")

    uncovered = sum(type_counts.get(et, 0) for et in NO_DICT_TYPES)
    print(f"  {'(无词典)':35s}: {uncovered:4d}  (类型: {', '.join(sorted(NO_DICT_TYPES))})")

    return 0


def _build_all(force: bool) -> int:
    """构建全部 6 个词典。"""
    from pipeline.cache_manager import get_extract_dir
    from pipeline.llm_client import LLMClient, LLMError

    extract_dir = get_extract_dir(_PROJECT_ROOT)
    entity_files = scan_entity_files(extract_dir)

    if not entity_files:
        print(f"未找到 Entity 数据文件: {extract_dir}")
        print("请先运行 Entity 抽取: python -m pipeline.entity_extractor <doc_id>")
        return 1

    print(f"endpoint : {extract_dir}")
    print(f"Entity 文件数: {len(entity_files)}")
    print()

    # 1. 收集 mention
    print("正在扫描 Entity 数据，收集 mention...")
    mentions_by_dict = collect_mentions(entity_files)

    # 统计
    total_mentions = 0
    for dn, types in mentions_by_dict.items():
        count = sum(len(mentions) for mentions in types.values())
        total_mentions += count
        type_summary = ", ".join(
            f"{et}({len(mentions)})" for et, mentions in types.items()
        )
        print(f"  {dn:35s}: {count:4d} mentions  ({type_summary})")

    if total_mentions == 0:
        print("\n没有收集到任何 mention，无法构建词典。")
        return 1

    print(f"\n总 mention 数: {total_mentions}")

    # 2. 构造 LLM 客户端
    try:
        client = LLMClient.from_env()
    except ValueError as exc:
        print(f"\n配置错误: {exc}")
        return 2

    print(f"\nLLM model: {client.model}")
    print(f"endpoint : {client._endpoint}")

    # 3. 逐个词典处理
    print("\n" + "=" * 80)
    print("开始构建词典")
    print("=" * 80)

    all_results: dict[str, Path] = {}

    for dict_name in DICT_MAPPING:
        mentions = mentions_by_dict.get(dict_name, {})

        # 跳过空的词典
        total_in_dict = sum(len(m) for m in mentions.values())
        if total_in_dict == 0:
            print(f"\n--- {dict_name} ---")
            print(f"  无 mention，跳过")
            all_results[dict_name] = _DICT_DIR / f"{dict_name}.csv"
            continue

        print(f"\n--- {dict_name} ---")
        print(f"  mention 数: {total_in_dict}")
        for et, mset in mentions.items():
            print(f"    {et}: {len(mset)} 个不同 mention")

        # 检查缓存
        if not force:
            cached = load_cache(dict_name)
            if cached is not None:
                print(f"  读取缓存: {get_cache_path(dict_name)}")
                print(f"  （如需重新生成，加 --force 参数）")
                entries = cached
            else:
                entries = None
        else:
            print(f"  --force 模式，强制重新生成")
            entries = None

        # 调用 LLM
        if entries is None:
            print(f"  正在调用 LLM 生成分组草案（可能需要 30-300 秒）...")
            try:
                entries = call_llm_for_dict(dict_name, mentions, client)
            except (ValueError, LLMError) as exc:
                print(f"  LLM 调用失败: {exc}")
                print(f"  跳过 {dict_name}")
                continue

            # 保存缓存
            cache_path = save_cache(dict_name, entries, client.model, total_in_dict)
            print(f"  已保存缓存: {cache_path}")

        # 4. 保存 CSV
        csv_path = save_dictionary_csv(dict_name, entries)
        print(f"  已保存词典: {csv_path}")
        print(f"  条目数量: {len(entries)}")

        all_results[dict_name] = csv_path

    # 5. 汇总
    print("\n" + "=" * 80)
    print("词典构建完成")
    print("=" * 80)
    for dn, path in all_results.items():
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        status = f"{size} bytes" if exists else "未生成"
        print(f"  {dn:35s}: {status}")

    print(f"\n词典目录: {_DICT_DIR}")
    print(f"缓存目录: {_CACHE_DIR}")

    return 0


def _main() -> int:
    """命令行入口。"""
    args = sys.argv[1:]

    if "--list" in args:
        return _list_entity_data()

    force = "--force" in args

    return _build_all(force)


if __name__ == "__main__":
    raise SystemExit(_main())
