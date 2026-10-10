"""统一抽取 Prompt 模板（方案 C：一步抽取 Entity + Relation + source_text）。

替代三阶段串行（Evidence→Entity→Relation）的根本问题：
    Evidence 预抽取太保守 → Entity 找不到合法 evidence_id → 被丢弃
    → Relation 找不到合法 head/tail_entity_id → 被丢弃
    级联误差放大，导致 Relation 数量极少（实测 BT000008: 25 ENT → 1 REL）。

方案 C 核心：
    1. 一次 LLM 调用同时生成 Entity + Relation
    2. 每条 Entity/Relation 直接带 source_text（原文片段，Python 后处理包装成 Evidence）
    3. Relation 通过 (mention, entity_type) 引用 Entity，不依赖 entity_id
    4. Python 后处理：
       - source_text → 包装成 Evidence（分配 evidence_id）
       - (mention, entity_type) → 匹配 entity_id
       - 反向关联 evidence.entities
    5. P7 校验仍做 Domain/Range + 原文溯源过滤

核心原则（Schema_rules §22 / Entity_schema §1 / Relation_schema §7.1-§7.4）：
    "宁可缺失，不得臆测"
    - mention / source_text 必须是原文逐字引用
    - Relation 必须由原文明确支持，不得依据医学常识、模型推理或实体共现
    - §7.2 不根据共现建立 Relation
    - §7.3 不根据医学常识补充 Relation
    - §7.4 保留否定和不确定关系
    - §8  Relation 必须具有明确方向
    - §7.1 具体化：Head/Tail 必须是原文明确的主宾语，禁止用文档主题实体回填主语
    - §7.1 具体化：Head/Tail 的 mention 必须逐字出现在该条 Relation 自己的 source_text 中
    - Domain/Range 不满足时的处理顺序：改用专用 relation_type → 无专用类型则舍弃该
      Relation；禁止用泛关系兜底，禁止为凑关系类型而改判实体类型
    - 句式级禁令（BT000001 Agent-Gold 抽查教训，EXTRACTION_SPEC §9.2.1）：
      目的状语/方法句、such-as 同位、纯时序表述都不断言关系，不得建边
    - 实体判型按**中心词**，且**影像手段限定语优先**：radiographic/MRI 限定的变化类属 ImagingFinding
      （观察结果），裸疾病过程词属 ClinicalFeature；两者都不得判 Disease。
      演进：v1 一律判 ImagingFinding、v2 一律判 Disease（均为无规则的直觉判型），v4 才定成可执行判据
    - 实体类型一致性：同一列举内的同构项必须同类型；同一所指不得双类型；
      Other 不是默认桶；抽取层不做同义合并（归一是标准化层职责）

输出格式：
    {
      "entities": [
        {
          "entity_type": "Disease",
          "mention": "acute ischemic stroke",
          "source_text": "Patients with acute ischemic stroke were enrolled...",
          "page": 3,
          "section": "Methods"
        }
      ],
      "relations": [
        {
          "head_mention": "acute ischemic stroke",
          "head_entity_type": "Disease",
          "relation_type": "HAS_FINDING",
          "tail_mention": "restricted diffusion",
          "tail_entity_type": "ImagingFinding",
          "assertion_type": "Positive",
          "source_text": "Restricted diffusion was observed on DWI in patients with acute ischemic stroke.",
          "page": 5,
          "section": "Results"
        }
      ]
    }

输入 / 输出：
    输入：metadata dict + markdown 文本
    输出：list[dict]（system message + user message，OpenAI chat messages 格式）
"""
from __future__ import annotations

from typing import Any, Final

# 复用 entity_prompt / relation_prompt 的枚举常量，确保与 Schema 完全一致
from pipeline.prompts.entity_prompt import ENTITY_TYPES
from pipeline.prompts.relation_prompt import (
    ASSERTION_TYPES,
    DISALLOWED_FOR_LLM,
    DOMAIN_RANGE,
    RELATION_TYPES,
)
from pipeline.prompts.disease_profiles import (
    DEFAULT_PROFILE,
    DiseaseProfile,
    merge_entity_examples,
)

# Evidence 类型（用于 source_text 的分类提示，由 Python 后处理推断）
EVIDENCE_TYPE_HINTS: Final[tuple[str, ...]] = (
    "Imaging Finding",
    "Clinical Finding",
    "Technical Finding",
    "Pathology Finding",
    "Genetic Finding",
    "Molecular Finding",
    "Study Design",
    "Treatment Outcome",
    "Prognostic Indicator",
    "Diagnostic Criterion",
    "Methodological Detail",
    "Study Population",
    "Guideline Recommendation",
    "Consensus Statement",
    "Drug Dosage",
    "Imaging Protocol",
    "Follow-up Data",
    "Other",
)


# --------------------------------------------------------------------------- #
# System Prompt 构建
# --------------------------------------------------------------------------- #
# Entity 类型的典型 mention 示例（帮助 LLM 正确判型）
_ENTITY_EXAMPLES: Final[dict[str, str]] = {
    "Disease": "如：glioma, acute ischemic stroke, Alzheimer's disease",
    "ImagingFinding": "如：restricted diffusion, hyperintensity, edema, lesion, atrophy",
    "MRISequence": "如：DWI, FLAIR, T1WI, T2WI, SWI, DTI",
    "Anatomy": "如：white matter, hippocampus, frontal lobe, basal ganglia",
    "Treatment": "如：radiation therapy, surgical resection, chemotherapy",
    "Biomarker": "如：fractional anisotropy, ADC, Ki-67, MBP",
    "Pathology": "如：necrosis, mitosis, vascular proliferation",
    "MolecularFeature": "如：IDH mutation, MGMT methylation",
    "GeneticFeature": "如：EGFR amplification, 1p/19q codeletion",
    "ClinicalFeature": "如：cognitive impairment, motor deficit, tumor progression",
    "Symptom": "如：headache, seizure, pain, fatigue",
    "RiskFactor": "如：age, hypertension, smoking",
    "Complication": "如：hemorrhage, infection, radiation necrosis",
    "StudyPopulation": "如：56 patients with glioma, healthy controls",
    "ImagingModality": "如：MRI, CT, PET, SPECT",
    "ContrastAgent": "如：gadolinium, Gd-DTPA",
    "Other": "仅当上述类型均不适用时使用",
}


# --------------------------------------------------------------------------- #
# 默认 fallback 常量（DEFAULT_PROFILE 无疾病系专属内容时使用）
# --------------------------------------------------------------------------- #
_DEFAULT_RELATION_PATTERNS: Final[str] = """### 关系发现模式（按论文类型匹配）

**临床论文**（病例报告/临床试验/队列研究）：
- "Patients with X showed Y on Z" → X(Disease) HAS_FINDING Y(ImagingFinding) + Y VISIBLE_ON Z(MRISequence)
- "X was located in Y" → X(ImagingFinding) LOCATED_IN Y(Anatomy)
- "X was treated with Y" → X(Disease) TREATED_BY Y(Treatment)
- "X had symptom Y" → X(Disease) HAS_SYMPTOM Y(Symptom)
- "X is a risk factor for Y" → Y(Disease) HAS_RISK_FACTOR X(RiskFactor)
- "X was diagnosed by Y" → X(Disease) DIAGNOSED_BY Y(ImagingModality/MRISequence)
- "X is associated with Y" → X ASSOCIATED_WITH Y
- "X predicts Y" → X PREDICTS Y

**方法学论文**（影像技术/DTI/fMRI/深度学习/新序列）— 关系更隐蔽，但**隐蔽不等于可以推断**：
- "X was observed on Y" → X(ImagingFinding) VISIBLE_ON Y(MRISequence)
- "X showed higher sensitivity than Y" → X COMPARED_WITH Y (assertion=Comparative)
- "X outperformed Y" / "X superior to Y" → X COMPARED_WITH Y (Comparative)
- "FA values were lower in patients with X" → X(Disease) ASSOCIATED_WITH FA(Biomarker) (Negative)
- "X is a marker of Y" / "X is indicative of Y" → X(Biomarker) ASSOCIATED_WITH Y(Disease)
- "X achieved dice coefficient of Y" → X ASSESSED_BY Y(Biomarker)
- "X is based on Y" / "X relies on Y" → X ASSOCIATED_WITH Y
- "X showed correlation with Y" → X CORRELATES_WITH Y
- "X improved detection of Y" → X IMPROVES Y
- "X may improve detection of Y" → X IMPROVES Y (Uncertain)

以下句式**不是**可建边的模式（它们陈述本研究的流程，属禁止事项 3 的方法句）：
`X was used to assess/evaluate Y`、`X was applied to Y`、`X imaging was performed to evaluate Y`、
`Signal intensity of X was measured`、`X was evaluated on Y`、`DTI measures FA in white matter`。
同一句若另有性能结果，只取该结果建边（如 "DWI was used to detect lesions, and detected 12 more than T2" → DWI COMPARED_WITH T2）。

**综述/指南论文**：
- "X is commonly associated with Y" → X ASSOCIATED_WITH Y
- "X predicts Y" → X PREDICTS Y
- "X improves Y" → X IMPROVES Y
- "X worsens Y" → X WORSENS Y"""

_DEFAULT_EXAMPLE_OUTPUT: Final[str] = """```json
{
  "entities": [
    {"entity_type": "Disease", "mention": "acute ischemic stroke", "source_text": "Patients with acute ischemic stroke were enrolled in this study.", "page": 3, "section": "Methods"},
    {"entity_type": "ImagingFinding", "mention": "restricted diffusion", "source_text": "Restricted diffusion was observed on DWI in patients with acute ischemic stroke.", "page": 5, "section": "Results"},
    {"entity_type": "MRISequence", "mention": "DWI", "source_text": "Restricted diffusion was observed on DWI in patients with acute ischemic stroke.", "page": 5, "section": "Results"}
  ],
  "relations": [
    {"head_mention": "acute ischemic stroke", "head_entity_type": "Disease", "relation_type": "HAS_FINDING", "tail_mention": "restricted diffusion", "tail_entity_type": "ImagingFinding", "assertion_type": "Positive", "source_text": "Restricted diffusion was observed on DWI in patients with acute ischemic stroke.", "page": 5, "section": "Results"},
    {"head_mention": "restricted diffusion", "head_entity_type": "ImagingFinding", "relation_type": "VISIBLE_ON", "tail_mention": "DWI", "tail_entity_type": "MRISequence", "assertion_type": "Positive", "source_text": "Restricted diffusion was observed on DWI in patients with acute ischemic stroke.", "page": 5, "section": "Results"}
  ]
}
```"""


def build_system_prompt(profile: DiseaseProfile | None = None) -> str:
    """构建 system prompt（静态，不随文献变化）。

    优化版（v2）：正面引导优先，负面规则精简，新增关系发现指南。
    v2.1：按疾病系 profile 注入专属实体示例、关系模式、判型提示等差异段。
    共享段（核心原则 / Entity-Relation 枚举 / Domain-Range / 禁止事项 / 检查清单）不变。
    """
    if profile is None:
        profile = DEFAULT_PROFILE

    # Entity 类型列表（带示例）——使用 profile 专属示例合并默认示例
    examples = merge_entity_examples(profile)
    entity_lines: list[str] = []
    for t in ENTITY_TYPES:
        ex = examples.get(t, "")
        entity_lines.append(f"- {t} — {ex}")
    entity_types_str = "\n".join(entity_lines)

    # Domain/Range 表格
    dr_lines: list[str] = []
    for rtype in RELATION_TYPES:
        head_types, tail_types, desc = DOMAIN_RANGE[rtype]
        head_str = " / ".join(head_types)
        tail_str = " / ".join(tail_types)
        dr_lines.append(f"- {rtype:36s} | {head_str:30s} → {tail_str:30s} | {desc}")
    domain_range_table = "\n".join(dr_lines)

    # V1 禁用的 relation_type
    disallowed_str = ", ".join(DISALLOWED_FOR_LLM)

    # 疾病系专属段（DEFAULT_PROFILE 用空串，下方用 fallback 填充）
    relation_patterns_section = profile.relation_patterns or _DEFAULT_RELATION_PATTERNS
    high_freq_section = profile.high_freq_entities
    classification_hints_section = profile.classification_hints
    assessment_scales_section = profile.assessment_scales
    example_output_section = profile.example_output or _DEFAULT_EXAMPLE_OUTPUT

    return f"""你是一名脑部 MRI 医学文献知识抽取专家。从文献 Markdown 原文中**一次性**抽取所有 Entity 和 Relation，每条附带 source_text（原文片段）。

## 核心原则
1. **mention / source_text 必须是原文逐字引用** — 不得改写、翻译、缩写
2. **宁可缺失，不得臆测** — 无法从原文确定的实体/关系不抽取
3. **Relation 必须由原文明确支持** — 同句出现两个实体≠有关系；"进行了DWI检查"≠"DWI诊断该疾病"
4. **保留否定/不确定关系** — "No association"→Negative，"may"→Uncertain，逐条抽取不合并
5. **Relation 方向不可交换** — Head→Tail 有语义方向

## ⚠ 关系抽取优先（重要，但不是配额）
抽取完实体后，**逐对回原文确认是否存在原文支持的 Relation**，重点检查方法学论文里隐蔽的 ASSESSED_BY / COMPARED_WITH / CORRELATES_WITH / IMPROVES。
**孤儿实体是合法的**：原文没断言的关系不得为了补高覆盖率而臆造（违反禁止事项 1/2/3）。判据只有一条——原句是否断言了该关系。
{high_freq_section}
{relation_patterns_section}
### Relation 主客体判定
1. head/tail的mention必须**逐字出现**在该Relation的source_text中（不够长则扩大引文）
2. head/tail必须是原文那句话的**主语和宾语**，不得用文档主题实体回填缺失主语
3. 分词短语/无主语句/纯名词短语不建关系

## Entity 类型（{len(ENTITY_TYPES)} 个，含示例）
{entity_types_str}

### Entity 字段
- entity_type（必填，枚举）：上述类型之一
- mention（必填）：原文逐字引用，保留原文大小写
- source_text（必填）：实体所在原文片段
- page（必填）：整数或null。**只取 marker 里 `page:` 后的数字**（`<!-- page: 7 printed: 1471 -->` → 7）；`printed:` 是期刊印刷页码，禁止写进 page。无 marker 或引文在首个 marker 之前 → null，禁止估算
- section（必填）：章节（Abstract/Methods/Results等），无则null

### 实体判型规则
- **按中心词判型**：多词mention取最后一个名词为中心词
- **影像限定语优先**：带 radiographic/MRI/on MRI/evidence of 的变化类→ImagingFinding；裸疾病过程词（tumor progression）→ClinicalFeature
- **中心词是影像征象名词**（lesion/atrophy/enhancement）→ImagingFinding
- **同一列举内同构项同类型**：A, B, and C 并列时不得分属不同类型
- **Other不是默认桶**：17类都不适用时才用Other
- **不抽泛化描述**：significant morbidity等笼统词不抽
- **不做同义合并**：缩写和全称各自保留，但类型必须一致
{classification_hints_section}
## Relation 类型（{len(RELATION_TYPES)} 个）及 Domain/Range
{domain_range_table}

### V1 禁用：{disallowed_str}

### Relation 字段
- head_mention / head_entity_type（必填）：头实体，必须出现在entities列表中
- relation_type（必填，枚举）
- tail_mention / tail_entity_type（必填）：尾实体，必须出现在entities列表中
- assertion_type（必填，枚举）：Positive/Negative/Uncertain/Conditional/Comparative/Recommendation/Association/Prediction/Unknown
- source_text（必填）：支持该Relation的原文片段
- page / section（必填）

## 禁止事项
1. **不得因共现建关系** — 同句出现≠有关系，需原文明确表达
2. **不得用医学常识补充** — "进行了DWI检查"≠"DWI诊断该疾病"
3. **不得用目的状语/方法句建关系** — "To assess X, we used Y"是研究目的不是结论。
   谓语命中即属方法句：`we examined/used/employed/acquired/enrolled`、`X was used/applied/performed/acquired/obtained/recorded/evaluated/assessed`、
   `X was performed to evaluate Y`、`patients underwent X`、`X sequences were available`、`with a … sequence/protocol/coil`
4. **不得用举例同位建关系** — "such as X"不构成ASSESSED_BY
5. **ASSESSED_BY 的 tail 必须是评估手段**（序列/模态/量表/指标）— 刺激范式、任务、刺激材料、线圈、扫描仪、软件、腰穿、活检都不行；V1 无对应类型则舍弃
6. **不得为引用他人研究的背景句建关系** — 同时满足①带引文标记（`(24)`/`[25]`/`Keating 1993`/`et al`）②带转述引导语（`in one reported series`/`it has been shown`/`as reported by`/`previously described`）③句中无 `we`/`our`/`in this study`/`the present study` 时舍弃；只带引文编号的本研究结论（"consistent with Smith et al. (24), we found…"）照常抽取
7. **Head/Tail 不得指同一所指** — 一方整词包含另一方（`caudate nucleus volume` LOCATED_IN `caudate nucleus`）即删除或改判层级
8. **Domain/Range不匹配时** — 改用专用类型→无则舍弃→禁止用泛关系兜底
9. **否定结果逐条抽取** — 每个"未发现关联"单独建一条Negative Relation
10. **图像产物不得判 ImagingModality** — `-gram/-image/-map/-scan/-picture` 结尾的是产物（venograms、MR images、perfusion maps），改判 ImagingFinding 或省略
11. **不抽取** — 作者/机构/期刊名、普通名词、OCR乱码、模型推断、句子片段

## 输出前检查
1. 每条 Relation 的 head_mention 和 tail_mention 是否都在 entities 列表中？
2. 未参与任何 Relation 的实体，是否逐个回原文确认过"确实没有原句断言"？确认过就保留为孤儿，**不得补边**
3. assertion_type 是否与原文语气一致？（may→Uncertain，no→Negative，than→Comparative）
4. 有无 Relation 的 source_text 命中禁止事项 3 的方法句谓语、或禁止事项 6 的引文背景句？有则删边
5. page 取的是 `page:` 后的数字而不是 `printed:` 吗？
{assessment_scales_section}
## 输出格式
{example_output_section}

## 重要：Relation 的 head_mention / tail_mention 必须在 entities 列表中已出现
"""


# --------------------------------------------------------------------------- #
# User Prompt 构建
# --------------------------------------------------------------------------- #
def build_user_prompt(metadata: dict[str, Any], markdown: str) -> str:
    """构建 user prompt（动态，随文献变化）。

    参数：
        metadata  文献元数据 dict（含 title/journal/year/document_type 等）
        markdown  MinerU OCR Markdown 文本（含 <!-- page: N --> 页码标记）
    """
    title = metadata.get("title", "")
    journal = metadata.get("journal", "")
    year = metadata.get("year", "")
    doc_type = metadata.get("document_type", "")

    meta_block = f"""## 文献元数据
- 标题: {title}
- 期刊: {journal} ({year})
- 类型: {doc_type}"""

    return f"""{meta_block}

## 文献原文（Markdown）

{markdown}

---

请从上述文献中抽取所有 Entity 和 Relation，按指定 JSON 格式输出。"""


# --------------------------------------------------------------------------- #
# 重试消息构建
# --------------------------------------------------------------------------- #
def build_retry_message(error_feedback: str, last_raw_response: str) -> str:
    """构建重试时的 user 消息（包含错误反馈）。

    参数：
        error_feedback   上次失败的错误描述
        last_raw_response 上次 LLM 的原始响应（截断显示）
    """
    preview = last_raw_response[:500] if last_raw_response else ""
    return f"""你上次的输出存在以下问题：

{error_feedback}

上次输出（前 500 字符预览）：
{preview}

请修正上述问题，重新输出完整的 JSON。确保：
1. mention / source_text 是原文逐字引用，大小写照原文
2. Relation 的 head_mention / tail_mention 在 entities 列表中存在，且逐字出现在 source_text 中
3. entity_type / relation_type / assertion_type 使用合法枚举值，不输出 RECOMMENDED_BY / OTHER
4. 严格遵守 Domain/Range 约束：不匹配时改用专用类型→无则删→禁止用泛关系兜底
5. head/tail 是原文明确的主语和宾语，不得回填文档主题实体
6. 实体判型按中心词，影像限定语优先：radiographic/MRI 限定→ImagingFinding，裸过程词→ClinicalFeature
7. 否定结论逐条建 Negative Relation，不合并不删除
8. ⚠ 必须检查：超过25%的实体未参与任何Relation→回顾原文，检查是否遗漏关系
9. 方法学论文要特别检查：ASSESSED_BY/COMPARED_WITH/CORRELATES_WITH/IMPROVES"""


# --------------------------------------------------------------------------- #
# 常量导出（供 extractor 使用）
# --------------------------------------------------------------------------- #
ENTITY_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "entity_type",
    "mention",
    "source_text",
    "page",
    "section",
)

RELATION_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "head_mention",
    "head_entity_type",
    "relation_type",
    "tail_mention",
    "tail_entity_type",
    "assertion_type",
    "source_text",
    "page",
    "section",
)
