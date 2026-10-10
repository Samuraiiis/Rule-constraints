"""Relation 抽取 Prompt 模板（严格对齐 Relation_schema §1-§11）。

构建 LLM 的 system + user prompt，指导从文献 Markdown 原文中抽取 Relation。

核心原则（Schema_rules §22 / Relation_schema §1 / §7.1-§7.4）：
    "宁可缺失，不得臆测" —— Relation 必须由原文明确支持，不得依据医学常识、
    模型推理或实体共现自动生成。
    §7.1 直接证据原则：只有原文明确表达两个 Entity 之间的关系时，才能建立 Relation。
    §7.2 不根据共现建立 Relation。
    §7.3 不根据医学常识补充 Relation。
    §7.4 保留否定和不确定关系（assertion_type=Negative / Uncertain）。
    §8  Relation 必须具有明确方向，不得任意交换 Head 和 Tail。

输出格式：
    {"relations": [{...}, ...]}
    每条 relation 不含 relation_id / document_id（由 runner 分配）。

输入 / 输出：
    输入：metadata dict + markdown 文本 + entities 列表（已分配 entity_id）
           + evidences 列表（已分配 evidence_id）
    输出：list[dict]（system message + user message，OpenAI chat messages 格式）
"""
from __future__ import annotations

from typing import Any, Final

# --------------------------------------------------------------------------- #
# 枚举值（直接从 relation.schema.json / Relation_schema §3 §5 抄录，确保与 Schema 完全一致）
# --------------------------------------------------------------------------- #
RELATION_TYPES: Final[tuple[str, ...]] = (
    "HAS_FINDING",
    "VISIBLE_ON",
    "LOCATED_IN",
    "DIAGNOSED_BY",
    "DIFFERENTIAL_DIAGNOSIS",
    "HAS_SYMPTOM",
    "HAS_RISK_FACTOR",
    "HAS_COMPLICATION",
    "TREATED_BY",
    "RECOMMENDED_BY",
    "PREDICTS",
    "ASSOCIATED_WITH",
    "ASSOCIATED_WITH_BIOMARKER",
    "ASSOCIATED_WITH_MOLECULAR_FEATURE",
    "ASSOCIATED_WITH_GENETIC_FEATURE",
    "HAS_PATHOLOGY",
    "ASSESSED_BY",
    "COMPARED_WITH",
    "IMPROVES",
    "WORSENS",
    "CORRELATES_WITH",
    "OTHER",
)

ASSERTION_TYPES: Final[tuple[str, ...]] = (
    "Positive",
    "Negative",
    "Uncertain",
    "Conditional",
    "Comparative",
    "Recommendation",
    "Association",
    "Prediction",
    "Unknown",
)

# Domain/Range 约束（Relation_schema §4）
# key: relation_type, value: (head_entity_types, tail_entity_types, 使用说明)
# "Entity" 表示任意 entity_type 均可
DOMAIN_RANGE: Final[dict[str, tuple[tuple[str, ...], tuple[str, ...], str]]] = {
    "HAS_FINDING": (("Disease",), ("ImagingFinding",), "疾病具有某影像学表现"),
    "VISIBLE_ON": (("ImagingFinding",), ("MRISequence",), "某影像表现可见于特定 MRI 序列"),
    "LOCATED_IN": (("ImagingFinding", "Disease", "Pathology"), ("Anatomy",), "病灶/疾病/病理位于某解剖结构"),
    "DIAGNOSED_BY": (
        ("Disease",),
        ("ImagingModality", "MRISequence"),
        "原文明确说明某检查用于诊断该疾病",
    ),
    "DIFFERENTIAL_DIAGNOSIS": (("Disease",), ("Disease",), "原文明确描述鉴别诊断"),
    "HAS_SYMPTOM": (("Disease",), ("Symptom",), "疾病与症状之间的明确关系"),
    "HAS_RISK_FACTOR": (("Disease",), ("RiskFactor",), "疾病与危险因素之间的明确关系"),
    "HAS_COMPLICATION": (("Disease",), ("Complication",), "疾病与并发症之间的明确关系"),
    "TREATED_BY": (("Disease",), ("Treatment",), "原文明确描述治疗方式"),
    "RECOMMENDED_BY": (
        ("Disease", "ImagingModality", "Treatment"),
        ("Other",),  # V1 无 Guideline/Consensus 实体类型
        "指南或共识明确推荐（V1 暂不生成，详见 system prompt 说明）",
    ),
    "PREDICTS": (("Entity",), ("Entity",), "原文明确描述预测关系"),
    "ASSOCIATED_WITH": (("Entity",), ("Entity",), "原文明确描述关联"),
    "ASSOCIATED_WITH_BIOMARKER": (("Disease",), ("Biomarker",), "疾病与生物标志物关联"),
    "ASSOCIATED_WITH_MOLECULAR_FEATURE": (
        ("Disease",),
        ("MolecularFeature",),
        "疾病与分子特征关联",
    ),
    "ASSOCIATED_WITH_GENETIC_FEATURE": (
        ("Disease",),
        ("GeneticFeature",),
        "疾病与遗传特征关联",
    ),
    "HAS_PATHOLOGY": (("Disease",), ("Pathology",), "疾病与病理特征关联"),
    "ASSESSED_BY": (("Entity",), ("Entity",), "某对象由某指标、方法或检查进行评估"),
    "COMPARED_WITH": (("Entity",), ("Entity",), "原文存在明确比较"),
    "IMPROVES": (("Entity",), ("Entity",), "原文明确说明改善作用"),
    "WORSENS": (("Entity",), ("Entity",), "原文明确说明恶化作用"),
    "CORRELATES_WITH": (("Entity",), ("Entity",), "原文明确说明相关性"),
    "OTHER": (("Entity",), ("Entity",), "暂无法归入既有 Relation 类型（仅人工审核用）"),
}

# 必填字段（LLM 必须输出的字段；relation_id/document_id 由 runner 填充）
REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "head_entity_id",
    "relation_type",
    "tail_entity_id",
    "assertion_type",
    "evidence_ids",
)

# 不应输出的字段——runner 填充
SYSTEM_FIELDS: Final[tuple[str, ...]] = (
    "relation_id",
    "document_id",
)

# V1 阶段不允许 LLM 生成的 relation_type（§4 特别说明 + §4 OTHER 限制）
# RECOMMENDED_BY 需要 Guideline/Consensus 实体，V1 暂无该实体类型
# OTHER 仅用于人工审核或 Ontology 扩展，不允许 LLM 自由生成
DISALLOWED_FOR_LLM: Final[tuple[str, ...]] = (
    "RECOMMENDED_BY",
    "OTHER",
)


# --------------------------------------------------------------------------- #
# System Prompt 构建
# --------------------------------------------------------------------------- #
def build_system_prompt() -> str:
    """构建 system prompt（静态，不随文献变化）。

    严格对齐 Relation_schema §1-§11，列出全部枚举值、Domain/Range 和规则。
    """
    # 构建 Domain/Range 表格文本
    dr_lines: list[str] = []
    for rtype in RELATION_TYPES:
        head_types, tail_types, desc = DOMAIN_RANGE[rtype]
        head_str = " / ".join(head_types)
        tail_str = " / ".join(tail_types)
        dr_lines.append(f"- {rtype:36s} | {head_str:30s} → {tail_str:30s} | {desc}")
    domain_range_table = "\n".join(dr_lines)

    return f"""你是一名脑部 MRI 医学文献关系抽取专家。你的任务是从文献 Markdown 原文中抽取 Relation（实体间的语义关系）。

## 核心原则（不可违背）
1. **直接证据原则**——只有原文明确表达两个 Entity 之间的关系时，才能建立 Relation
2. **不根据共现建立 Relation**——同一句或同一段同时出现两个实体，不等于原文明确表达关系
3. **不根据医学常识补充 Relation**——"进行了 DWI 检查"不等于"DWI 用于诊断该疾病"
4. **宁可缺失，不得臆测**——无法从原文明确确认的关系不抽取
5. **保留否定和不确定关系**——"No significant association"应建 Relation 并标 assertion_type=Negative
6. **方向不可交换**——Head 和 Tail 必须严格遵循 Domain/Range，不得任意交换
7. **必须引用真实 ID**——head_entity_id / tail_entity_id 必须来自用户提供的 Entity ID 清单，evidence_ids 必须来自用户提供的 Evidence ID 清单

## relation_type（必填，枚举，{len(RELATION_TYPES)} 个）
允许值：
{chr(10).join(f"- {rt}" for rt in RELATION_TYPES)}

## Domain/Range 约束（Head → Tail 方向）
"Entity" 表示任意 entity_type 均可。Head/Tail 必须使用对应类型的实体。

{domain_range_table}

## V1 阶段限制
- **RECOMMENDED_BY**：需要 Guideline/Consensus 实体，当前 Entity 体系暂无该类型，**V1 不生成 RECOMMENDED_BY Relation**。相关推荐内容保留在 Evidence（evidence_type=Guideline Recommendation / Consensus Statement）中。
- **OTHER**：仅用于人工审核或 Ontology 扩展，**不允许 LLM 自由生成**。无法归类的关系应省略，不得用 OTHER 兜底。

## assertion_type（必填，枚举，{len(ASSERTION_TYPES)} 个）
允许值：
- Positive — 原文明确肯定该关系
- Negative — 原文明确否定该关系（如 "No significant association"）
- Uncertain — 原文使用 "may/might/could/possible" 等不确定表述
- Conditional — 关系依赖特定条件（如 "in elderly patients"）
- Comparative — 原文存在比较（如 "higher sensitivity than"）
- Recommendation — 原文为推荐性表述
- Association — 原文描述关联性
- Prediction — 原文描述预测性
- Unknown — 原文表述性质不明确

## Relation 字段说明

### head_entity_id（必填，string）
头实体 ID。**必须从用户提供的 Entity ID 清单中选取，不得编造。**
Head 的 entity_type 必须符合该 relation_type 的 Domain 约束。

### relation_type（必填，枚举）
关系类型。严格使用上述允许值，不得编造。
V1 阶段不得使用 RECOMMENDED_BY 和 OTHER。

### tail_entity_id（必填，string）
尾实体 ID。**必须从用户提供的 Entity ID 清单中选取，不得编造。**
Tail 的 entity_type 必须符合该 relation_type 的 Range 约束。
head_entity_id 与 tail_entity_id 不得相同（禁止自环）。

### assertion_type（必填，枚举）
关系的陈述性质。严格使用上述允许值。

### evidence_ids（必填，array[string]）
支持该 Relation 的 Evidence ID 列表。至少 1 个。
**必须从用户提供的 Evidence ID 清单中选取，不得编造不存在的 ID。**
一条 Relation 可由多条 Evidence 共同支持。

## 抽取原则示例

### 示例 1：直接证据（HAS_FINDING + VISIBLE_ON）
原文：
> Restricted diffusion was observed on DWI in patients with acute ischemic stroke.

可建立：
- acute ischemic stroke (Disease) ── HAS_FINDING ──→ Restricted diffusion (ImagingFinding) | assertion=Positive
- Restricted diffusion (ImagingFinding) ── VISIBLE_ON ──→ DWI (MRISequence) | assertion=Positive

### 示例 2：共现不建关系
原文（同一句出现）：
> Glioblastoma, DWI, FLAIR, Edema were mentioned.

不得仅因共现就建立 HAS_FINDING / VISIBLE_ON 关系，必须检查原文是否明确支持。

### 示例 3：否定关系保留
原文：
> No significant association was found between X and Y.

可建立：
- X ── ASSOCIATED_WITH ──→ Y | assertion=Negative

### 示例 4：不确定标记
原文：
> DWI may improve detection of small acute infarcts.

可建立：
- DWI ── IMPROVES ──→ detection of small acute infarcts | assertion=Uncertain

## 不输出的字段（由系统填充）
- relation_id（由系统分配）
- document_id（由系统填充）

## 输出格式
返回一个 JSON 对象：
```json
{{
  "relations": [
    {{
      "head_entity_id": "BT000001-ENT-xxxxxxxx",
      "relation_type": "HAS_FINDING",
      "tail_entity_id": "BT000001-ENT-yyyyyyyy",
      "assertion_type": "Positive",
      "evidence_ids": ["BT000001-EV-zzzzzzzz"]
    }}
  ]
}}
```

如果文献内容与脑部 MRI 无关，或原文未明确表达任何实体间关系，返回空数组：`{{"relations": []}}`

## 抽取要求
1. 每条 Relation 必须有至少 1 条 Evidence 支持
2. head_entity_id / tail_entity_id 必须来自用户提供的 Entity ID 清单
3. evidence_ids 必须来自用户提供的 Evidence ID 清单
4. 同一组 (head, relation_type, tail) 在同一文献中只抽取一次（系统会合并 evidence_ids）
5. 严格使用上述枚举值，不得编造
6. V1 不得使用 RECOMMENDED_BY 和 OTHER
7. head_entity_id 与 tail_entity_id 不得相同
8. Head/Tail 的 entity_type 必须符合 Domain/Range 约束
"""


# --------------------------------------------------------------------------- #
# User Prompt 构建
# --------------------------------------------------------------------------- #
def build_user_prompt(
    metadata: dict[str, Any],
    markdown: str,
    entities: list[dict[str, Any]],
    evidences: list[dict[str, Any]],
) -> str:
    """构建 user prompt（动态，含文献元数据 + Entity ID 清单 + Evidence ID 清单 + Markdown 原文）。

    参数：
        metadata   document_metadata.csv 行（含 title/journal/year 等）
        markdown   MinerU OCR Markdown 文本（可能含 <!-- page: N --> 标记）
        entities   已分配 entity_id 的 Entity 列表（供 LLM 引用 head/tail）
        evidences  已分配 evidence_id 的 Evidence 列表（供 LLM 引用 evidence_ids）
    """
    title = metadata.get("title", "") or "（无标题）"
    journal = metadata.get("journal", "") or "（无期刊）"
    year = metadata.get("year", "") or "（无年份）"
    doc_type = metadata.get("document_type", "") or "（无类型）"
    study_type = metadata.get("study_type", "") or "（无研究类型）"

    # 构建 Entity ID 清单（entity_id | entity_type | mention | source_text 摘要）
    ent_lines: list[str] = []
    for ent in entities:
        eid = ent.get("entity_id", "?")
        etype = ent.get("entity_type", "?")
        mention = ent.get("mention", "")
        src = ent.get("source_text", "")
        # 截断过长的 source_text（避免 token 爆炸）
        if len(src) > 100:
            src = src[:100] + "..."
        ent_lines.append(f"- {eid} | {etype} | mention: {mention} | source: {src}")

    entity_list = (
        "\n".join(ent_lines) if ent_lines else "（无 Entity）"
    )

    # 构建 Evidence ID 清单（evidence_id | evidence_type | evidence_statement 摘要）
    ev_lines: list[str] = []
    for ev in evidences:
        eid = ev.get("evidence_id", "?")
        etype = ev.get("evidence_type", "?")
        stmt = ev.get("evidence_statement", "")
        # 截断过长的 statement（避免 token 爆炸）
        if len(stmt) > 200:
            stmt = stmt[:200] + "..."
        ev_lines.append(f"- {eid} | {etype} | {stmt}")

    evidence_list = "\n".join(ev_lines) if ev_lines else "（无 Evidence）"

    return f"""## 文献元数据
- 标题：{title}
- 期刊：{journal}
- 年份：{year}
- 文献类型：{doc_type}
- 研究类型：{study_type}

## 可用 Entity ID 清单（head_entity_id / tail_entity_id 必须从中选取）
{entity_list}

## 可用 Evidence ID 清单（evidence_ids 必须从中选取）
{evidence_list}

## 文献原文（Markdown）
{markdown}

---
请按照系统指令从上述文献中抽取 Relation，返回 JSON 对象。
head_entity_id / tail_entity_id 必须从上面的 Entity ID 清单中选取，不得编造不存在的 ID。
evidence_ids 必须从上面的 Evidence ID 清单中选取，不得编造不存在的 ID。
V1 不得使用 RECOMMENDED_BY 和 OTHER。
"""


def build_retry_message(error_feedback: str) -> str:
    """构建重试时的 user 纠正提示（含具体错误信息）。

    参数：
        error_feedback  上次失败的错误描述（如 "INVALID_JSON: 返回的不是合法 JSON"）
    """
    return (
        f"你上次的输出存在问题：{error_feedback}\n"
        "请修正问题后重新输出 JSON 对象（包含 \"relations\" 数组）。"
        "确保返回合法 JSON，所有枚举值使用上述指定值，必填字段不可缺失，"
        "head_entity_id / tail_entity_id 必须从提供的 Entity ID 清单中选取，"
        "evidence_ids 必须从提供的 Evidence ID 清单中选取，"
        "不得使用 RECOMMENDED_BY 和 OTHER。"
    )
