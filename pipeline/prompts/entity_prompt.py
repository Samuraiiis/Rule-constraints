"""Entity 抽取 Prompt 模板（严格对齐 Entity_schema §1-§11）。

构建 LLM 的 system + user prompt，指导从文献 Markdown 原文中抽取 Entity。

核心原则（Schema_rules §22 / Entity_schema §1）：
    "宁可缺失，不得臆测" —— mention 必须是原文逐字引用，不得用模型医学常识补充。
    "LLM 负责发现实体，词典/本体负责标准化"（Entity_schema §9）。

输出格式：
    {"entities": [{...}, ...]}
    每条 entity 不含 entity_id / document_id / canonical_name / ontology_id（由 runner/normalizer 填充）。

输入 / 输出：
    输入：metadata dict + markdown 文本 + evidences 列表（已分配 evidence_id）
    输出：list[dict]（system message + user message，OpenAI chat messages 格式）
"""
from __future__ import annotations

from typing import Any, Final

# --------------------------------------------------------------------------- #
# 枚举值（直接从 entity.schema.json / Entity_schema §3 抄录，确保与 Schema 完全一致）
# --------------------------------------------------------------------------- #
ENTITY_TYPES: Final[tuple[str, ...]] = (
    "Disease",
    "ImagingFinding",
    "MRISequence",
    "Anatomy",
    "Treatment",
    "Biomarker",
    "Pathology",
    "MolecularFeature",
    "GeneticFeature",
    "ClinicalFeature",
    "Symptom",
    "RiskFactor",
    "Complication",
    "StudyPopulation",
    "ImagingModality",
    "ContrastAgent",
    "Other",
)

# 必填字段（LLM 必须输出的字段；entity_id/document_id 由 runner 填充）
REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "entity_type",
    "mention",
    "source_text",
    "page",
    "section",
    "evidence_ids",
)

# 不应输出的字段——runner 填充
SYSTEM_FIELDS: Final[tuple[str, ...]] = (
    "entity_id",
    "document_id",
)

# 不应输出的字段——normalizer 填充
NORMALIZER_FIELDS: Final[tuple[str, ...]] = (
    "canonical_name",
    "ontology_id",
)


# --------------------------------------------------------------------------- #
# System Prompt 构建
# --------------------------------------------------------------------------- #
def build_system_prompt() -> str:
    """构建 system prompt（静态，不随文献变化）。

    严格对齐 Entity_schema §1-§11，列出全部枚举值和规则。
    """
    return f"""你是一名脑部 MRI 医学文献实体抽取专家。你的任务是从文献 Markdown 原文中抽取 Entity（医学实体）。

## 核心原则（不可违背）
1. **mention 必须是文献原文的逐字引用**——不得改写、翻译、缩写或由你生成
2. **source_text 必须来自原始文献**——实体所在的原文片段，不得由你生成
3. **宁可缺失，不得臆测**——无法从原文确定的实体不抽取
4. **不得使用你的医学常识补充信息**——所有实体必须来自原文
5. **不得编造 Evidence ID**——evidence_ids 必须从用户提供的 Evidence ID 列表中选取
6. **Other 不得作为默认分类**——无法确定类型时优先省略该实体

## entity_type（必填，枚举）
允许值（{len(ENTITY_TYPES)} 个）：
- Disease — 疾病或疾病实体
- ImagingFinding — 影像学表现、征象、信号、形态等
- MRISequence — DWI、ADC、T1WI、T2WI、FLAIR、SWI 等 MRI 序列
- Anatomy — 脑组织、血管、脑区、解剖结构
- Treatment — 治疗方式或治疗措施
- Biomarker — 临床或影像生物标志物
- Pathology — 病理学实体或病理表现
- MolecularFeature — 分子特征
- GeneticFeature — 基因或遗传特征
- ClinicalFeature — 临床特征
- Symptom — 症状
- RiskFactor — 危险因素
- Complication — 并发症
- StudyPopulation — 研究人群
- ImagingModality — MRI、CT、PET 等影像检查方式
- ContrastAgent — 影像增强剂
- Other — 确实无法归入上述类型的实体

## Entity 字段说明

### entity_type（必填，枚举）
实体的类型。严格使用上述允许值，不得编造。

### mention（必填，string）
原文中实体实际出现的表述。必须是原文逐字引用，不得标准化、翻译或改写。
例如：原文写 "acute ischemic stroke"，mention = "acute ischemic stroke"。
不得将 "AIS" 改写为 "acute ischemic stroke"。

### source_text（必填，string）
实体所在的原始文献文本。必须来自原始文献，应尽可能包含能够明确识别该 Entity 的上下文。

### page（必填，integer 或 null）
实体所在原始 PDF 页码。页码从 1 开始。如果 Markdown 中有 `<!-- page: N -->` 标记，请使用该页码。如无标记且无法确定，为 null。不得估算页码。

### section（必填，string 或 null）
实体在文献中的章节。优先使用原文章节名称（如 Abstract/Methods/Results/Discussion）。Markdown 中的 `#` 或 `##` 标题标记了章节，据此判断。不存在明确章节时为 null。

### evidence_ids（必填，array[string]）
支持当前 Entity 的 Evidence ID 列表。至少 1 个。
**必须从用户提供的 Evidence ID 列表中选取，不得编造不存在的 ID。**
一个 Entity 可以由多条 Evidence 共同支持。

## 不输出的字段（由系统填充）
- entity_id（由系统分配）
- document_id（由系统填充）
- canonical_name（由词典标准化填充）
- ontology_id（由词典标准化填充）

## 应抽取的实体
- 疾病
- MRI 序列
- 影像学表现
- 解剖结构
- 临床表现
- 症状
- 治疗
- 生物标志物
- 分子/遗传特征
- 病理特征
- 风险因素
- 并发症
- 研究人群
- 影像检查方式
- 对比剂

## 不应抽取的实体
- 普通医学常用词但没有实体语义的词
- 作者、机构、期刊名称
- 无医学意义的普通名词
- OCR 乱码
- 模型推断产生的实体

## 输出格式
返回一个 JSON 对象：
```json
{{
  "entities": [
    {{
      "entity_type": "Disease",
      "mention": "acute ischemic stroke",
      "source_text": "Patients with acute ischemic stroke were enrolled...",
      "page": 3,
      "section": "Methods",
      "evidence_ids": ["E000001", "000005"]
    }}
  ]
}}
```

如果文献内容与脑部 MRI 无关，或无法抽取到任何实体，返回空数组：`{{"entities": []}}`

## 抽取要求
1. 每个 Entity 必须有至少 1 条 Evidence 支持
2. mention 必须与原文完全一致，不得改写
3. source_text 必须包含该 mention 的上下文
4. 同一原文中多次出现的同一实体，只抽取一次（mention 相同则合并 evidence_ids）
5. 严格使用上述 entity_type 枚举值，不得编造
6. 如 Markdown 中有 `<!-- page: N -->` 标记，该标记之后的文本属于第 N 页
"""


# --------------------------------------------------------------------------- #
# User Prompt 构建
# --------------------------------------------------------------------------- #
def build_user_prompt(
    metadata: dict[str, Any],
    markdown: str,
    evidences: list[dict[str, Any]],
) -> str:
    """构建 user prompt（动态，含文献元数据 + Evidence ID 清单 + Markdown 原文）。

    参数：
        metadata   document_metadata.csv 行（含 title/journal/year 等）
        markdown   MinerU OCR Markdown 文本（可能含 <!-- page: N --> 标记）
        evidences  已分配 evidence_id 的 Evidence 列表
    """
    title = metadata.get("title", "") or "（无标题）"
    journal = metadata.get("journal", "") or "（无期刊）"
    year = metadata.get("year", "") or "（无年份）"
    doc_type = metadata.get("document_type", "") or "（无类型）"
    study_type = metadata.get("study_type", "") or "（无研究类型）"

    # 构建 Evidence ID 清单（只展示 evidence_id + evidence_type + evidence_statement 摘要）
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

## 可用 Evidence ID 列表（evidence_ids 必须从中选取）
{evidence_list}

## 文献原文（Markdown）
{markdown}

---
请按照系统指令从上述文献中抽取 Entity，返回 JSON 对象。
evidence_ids 必须从上面的 Evidence ID 列表中选取，不得编造不存在的 ID。
"""


def build_retry_message(error_feedback: str) -> str:
    """构建重试时的 user 纠正提示（含具体错误信息）。

    参数：
        error_feedback  上次失败的错误描述（如 "INVALID_JSON: 返回的不是合法 JSON"）
    """
    return (
        f"你上次的输出存在问题：{error_feedback}\n"
        "请修正问题后重新输出 JSON 对象（包含 \"entities\" 数组）。"
        "确保返回合法 JSON，所有枚举值使用上述指定值，必填字段不可缺失，"
        "evidence_ids 必须从提供的 Evidence ID 列表中选取。"
    )
