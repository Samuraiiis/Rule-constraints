"""疾病系专属 Profile（v2 分疾病系抽取规则）。

按 document_id 前缀（BT/CV/NL/PS）选择对应疾病系 profile，
将疾病系专属的实体示例、关系模式、判型提示等注入 system prompt。

共享层（核心原则 / Entity-Relation 枚举 / Domain-Range / 禁止事项 / 检查清单）
在 unified_prompt.build_system_prompt() 中保持不变，profile 仅覆盖差异段。

文档对应：
    AGENT_INSTRUCTION.md（共享基础） + disease_bt/cv/nl/ps.md（疾病系专属）
    位于 docs/v2/ 目录。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DiseaseProfile:
    """疾病系专属抽取 profile。

    字段对应 system prompt 的 6 个差异段，由 build_system_prompt() 注入。
    共享段（核心原则、枚举、Domain/Range、禁止事项、检查清单、输出格式）不受影响。
    """

    name: str
    """疾病系名称，如 '脑肿瘤' / '脑血管疾病' / '神经内科疾病' / '精神类疾病'"""

    doc_id_prefixes: tuple[str, ...]
    """document_id 前缀，如 ('BT',) / ('CV',)"""

    entity_examples: dict[str, str] = field(default_factory=dict)
    """entity_type → 疾病系专属典型 mention 示例；缺失的 type 由默认示例兜底"""

    high_freq_entities: str = ""
    """高频遗漏清单（疾病系专属），注入到"关系抽取优先"段"""

    relation_patterns: str = ""
    """关系发现模式（含临床/方法学/综述子节），替换按论文类型的通用模式"""

    classification_hints: str = ""
    """疾病系专属判型提示，追加到实体判型规则之后"""

    assessment_scales: str = ""
    """评估量表识别（疾病系专属），注入 ASSESSED_BY 相关段"""

    example_output: str = ""
    """完整 JSON 输出示例（疾病系专属）"""


# --------------------------------------------------------------------------- #
# 默认 Entity 示例（DEFAULT_PROFILE 与各 profile 未覆盖的 type 使用）
# --------------------------------------------------------------------------- #
_DEFAULT_ENTITY_EXAMPLES: dict[str, str] = {
    "Disease": "如：glioma, acute ischemic stroke, Alzheimer's disease",
    "ImagingFinding": "如：edema, mass effect, restricted diffusion, hyperintensity, atrophy, lesion",
    "MRISequence": "如：DWI, FLAIR, T1WI, T2WI, SWI, DTI, ADC",
    "Anatomy": "如：white matter, hippocampus, frontal lobe, basal ganglia",
    "Treatment": "如：radiation therapy, chemotherapy, surgical resection",
    "Biomarker": "如：Ki-67, MGMT methylation, EGFR, fractional anisotropy, ADC",
    "Pathology": "如：necrosis, vascular proliferation, mitosis",
    "MolecularFeature": "如：IDH mutation, MGMT methylation",
    "GeneticFeature": "如：EGFR amplification, 1p/19q codeletion, PTEN mutation",
    "ClinicalFeature": "如：cognitive decline, memory loss, motor deficit, tumor progression",
    "Symptom": "如：headache, seizure, pain, fatigue",
    "RiskFactor": "如：age, hypertension, smoking",
    "Complication": "如：hemorrhage, infection, radiation necrosis",
    "StudyPopulation": "如：56 patients with recurrent brain tumors, healthy controls",
    "ImagingModality": "如：MRI, CT, PET, SPECT",
    "ContrastAgent": "如：gadolinium, Gd-DTPA",
    "Other": "仅当上述类型均不适用时使用（评估量表如 KPS/MMSE 也归此类）",
}


# --------------------------------------------------------------------------- #
# Profile 1: 脑肿瘤（BT）
# --------------------------------------------------------------------------- #
BT_PROFILE = DiseaseProfile(
    name="脑肿瘤",
    doc_id_prefixes=("BT",),
    entity_examples={
        "Disease": "如：glioblastoma, anaplastic astrocytoma, brain metastases, meningioma, medulloblastoma",
        "ImagingFinding": "如：edema, mass effect, contrast enhancement, restricted diffusion, necrosis, lesion",
        "MRISequence": "如：T1WI, T2WI, FLAIR, DWI, SWI, DTI, PWI, MRS",
        "Anatomy": "如：frontal lobe, temporal lobe, basal ganglia, thalamus, corpus callosum, cerebellum",
        "Treatment": "如：surgical resection, radiation therapy, chemotherapy, temozolomide, bevacizumab",
        "Biomarker": "如：Ki-67, ADC, rCBV, FA, choline, NAA/Cr ratio",
        "Pathology": "如：necrosis, vascular proliferation, mitosis, microvascular proliferation",
        "MolecularFeature": "如：IDH mutation, MGMT methylation, TERT promoter mutation, BRAF V600E",
        "GeneticFeature": "如：1p/19q codeletion, EGFR amplification, PTEN mutation, TP53 mutation",
        "ClinicalFeature": "如：tumor progression, radiographic response, cognitive decline",
        "Symptom": "如：headache, seizure, nausea, visual disturbance, weakness",
        "RiskFactor": "如：age, radiation exposure, genetic syndromes (NF1/NF2)",
        "Complication": "如：radiation necrosis, neurotoxicity, hemorrhage, infection",
        "StudyPopulation": "如：56 patients with recurrent glioma, healthy controls",
        "ImagingModality": "如：MRI, CT, PET, SPECT",
        "ContrastAgent": "如：gadolinium, Gd-DTPA, Gd-DOTA",
        "Other": "如：KPS (Karnofsky Performance Scale)",
    },
    high_freq_entities="""### ⚠ 高频遗漏清单（脑肿瘤）

1. **Disease → HAS_FINDING → ImagingFinding**：肿瘤有什么影像表现？（contrast enhancement, edema, mass effect, restricted diffusion）
2. **ImagingFinding → VISIBLE_ON → MRISequence**：影像表现在哪个序列？（enhancement on T1WI+Gd, restricted diffusion on DWI, perfusion on PWI）
3. **Disease → LOCATED_IN → Anatomy**：肿瘤位于哪个脑区？
4. **MolecularFeature → ASSOCIATED_WITH → Disease**：IDH突变与预后的关联
5. **Disease → TREATED_BY → Treatment**：手术/化疗/放疗
6. **Disease → HAS_PATHOLOGY → Pathology**：肿瘤的病理特征（necrosis, mitosis, vascular proliferation）
7. **Disease → DIAGNOSED_BY → ImagingModality**：MRI诊断""",
    relation_patterns="""### 关系发现模式（脑肿瘤）

**临床论文**：
- "Patients with X showed Y on Z" → X(Disease) HAS_FINDING Y(ImagingFinding) + Y VISIBLE_ON Z(MRISequence)
- "X was located in the Y lobe" → X(Disease/ImagingFinding) LOCATED_IN Y(Anatomy)
- "X was treated with Y" → X(Disease) TREATED_BY Y(Treatment: resection/chemo/radiotherapy)
- "IDH mutant gliomas showed better prognosis" → MolecularFeature ASSOCIATED_WITH Disease
- "X showed contrast enhancement" → X(ImagingFinding) VISIBLE_ON contrast-enhanced T1WI
- "KPS score was X" → Disease ASSESSED_BY KPS(Other)
- "X is associated with Y" → X ASSOCIATED_WITH Y

**方法学论文**：
- "X was observed on Y" → X(ImagingFinding) VISIBLE_ON Y(MRISequence)
- "X showed higher sensitivity than Y" → X COMPARED_WITH Y (Comparative)
- "rCBV values were higher in X" → X(Disease) ASSOCIATED_WITH rCBV(Biomarker)
- "X is a marker of Y" → X(Biomarker) ASSOCIATED_WITH Y(Disease)
- "FA was decreased in the X tract" → X(Anatomy) ASSOCIATED_WITH FA(Biomarker) (Negative)
- "X showed correlation with Y" → X CORRELATES_WITH Y

**综述/指南论文**：
- "X is commonly associated with Y" → X ASSOCIATED_WITH Y
- "X predicts Y" → X PREDICTS Y""",
    classification_hints="""### 判型提示（脑肿瘤）

- "tumor progression" / "radiographic failure" → ClinicalFeature（非 Disease）
- "enhancing tumor" → ImagingFinding
- "IDH mutation" → MolecularFeature（非 GeneticFeature——分子检测结果）
- "1p/19q codeletion" → GeneticFeature（染色体层面变异）
- "MGMT methylation" → MolecularFeature（分子特征，非 GeneticFeature）
- "necrosis" → Pathology（病理特征）；但在影像语境（"necrosis on MRI"）→ ImagingFinding
- "Ki-67" → Biomarker（增殖指标）
- "WHO grade" → 不是实体，是 Disease 的描述信息
- "mass effect" / "midline shift" → ImagingFinding""",
    assessment_scales="""### 评估量表（脑肿瘤）

- KPS (Karnofsky Performance Scale) → Other 类型，作 ASSESSED_BY 的 tail
- "KPS score was 80" → Disease ASSESSED_BY KPS
- 量表 carve-out：方法句 "Patients were assessed with KPS" 照常建边""",
    example_output="""### 完整示例（脑肿瘤）

```json
{
  "document_id": "BT000042",
  "entities": [
    {"entity_type": "Disease", "mention": "glioblastoma", "source_text": "Patients with glioblastoma underwent surgical resection followed by radiation therapy.", "page": 3, "section": "Methods"},
    {"entity_type": "ImagingFinding", "mention": "contrast enhancement", "source_text": "Contrast enhancement was observed on T1WI in the tumor bed.", "page": 5, "section": "Results"},
    {"entity_type": "MRISequence", "mention": "T1WI", "source_text": "Contrast enhancement was observed on T1WI in the tumor bed.", "page": 5, "section": "Results"},
    {"entity_type": "Pathology", "mention": "necrosis", "source_text": "Histopathological examination revealed necrosis and microvascular proliferation.", "page": 6, "section": "Results"},
    {"entity_type": "MolecularFeature", "mention": "IDH mutation", "source_text": "IDH mutation was associated with better overall survival in glioblastoma patients.", "page": 7, "section": "Discussion"},
    {"entity_type": "Anatomy", "mention": "frontal lobe", "source_text": "The tumor was located in the right frontal lobe.", "page": 4, "section": "Methods"},
    {"entity_type": "Treatment", "mention": "surgical resection", "source_text": "Patients with glioblastoma underwent surgical resection followed by radiation therapy.", "page": 3, "section": "Methods"},
    {"entity_type": "Other", "mention": "KPS", "source_text": "KPS was assessed at baseline and at 6-month follow-up.", "page": 3, "section": "Methods"}
  ],
  "relations": [
    {"head_mention": "glioblastoma", "head_entity_type": "Disease", "relation_type": "HAS_FINDING", "tail_mention": "contrast enhancement", "tail_entity_type": "ImagingFinding", "assertion_type": "Positive", "source_text": "Contrast enhancement was observed on T1WI in the tumor bed.", "page": 5, "section": "Results"},
    {"head_mention": "contrast enhancement", "head_entity_type": "ImagingFinding", "relation_type": "VISIBLE_ON", "tail_mention": "T1WI", "tail_entity_type": "MRISequence", "assertion_type": "Positive", "source_text": "Contrast enhancement was observed on T1WI in the tumor bed.", "page": 5, "section": "Results"},
    {"head_mention": "glioblastoma", "head_entity_type": "Disease", "relation_type": "LOCATED_IN", "tail_mention": "frontal lobe", "tail_entity_type": "Anatomy", "assertion_type": "Positive", "source_text": "The tumor was located in the right frontal lobe.", "page": 4, "section": "Methods"},
    {"head_mention": "glioblastoma", "head_entity_type": "Disease", "relation_type": "TREATED_BY", "tail_mention": "surgical resection", "tail_entity_type": "Treatment", "assertion_type": "Positive", "source_text": "Patients with glioblastoma underwent surgical resection followed by radiation therapy.", "page": 3, "section": "Methods"},
    {"head_mention": "glioblastoma", "head_entity_type": "Disease", "relation_type": "ASSESSED_BY", "tail_mention": "KPS", "tail_entity_type": "Other", "assertion_type": "Positive", "source_text": "KPS was assessed at baseline and at 6-month follow-up.", "page": 3, "section": "Methods"},
    {"head_mention": "glioblastoma", "head_entity_type": "Disease", "relation_type": "ASSOCIATED_WITH_MOLECULAR_FEATURE", "tail_mention": "IDH mutation", "tail_entity_type": "MolecularFeature", "assertion_type": "Positive", "source_text": "IDH mutation was associated with better overall survival in glioblastoma patients.", "page": 7, "section": "Discussion"},
    {"head_mention": "glioblastoma", "head_entity_type": "Disease", "relation_type": "HAS_PATHOLOGY", "tail_mention": "necrosis", "tail_entity_type": "Pathology", "assertion_type": "Positive", "source_text": "Histopathological examination revealed necrosis and microvascular proliferation.", "page": 6, "section": "Results"}
  ]
}
```""",
)


# --------------------------------------------------------------------------- #
# Profile 2: 脑血管疾病（CV）
# --------------------------------------------------------------------------- #
CV_PROFILE = DiseaseProfile(
    name="脑血管疾病",
    doc_id_prefixes=("CV",),
    entity_examples={
        "Disease": "如：ischemic stroke, intracerebral hemorrhage (ICH), subarachnoid hemorrhage (SAH), AVM, aneurysm, carotid stenosis, vasospasm",
        "ImagingFinding": "如：infarct, penumbra, hematoma, restricted diffusion, mass effect, blooming artifact, microbleeds",
        "MRISequence": "如：DWI, MRA, PWI, FLAIR, SWI, GRE, T2WI, ASL",
        "Anatomy": "如：MCA territory, ACA territory, PCA territory, basal ganglia, thalamus, internal capsule",
        "Treatment": "如：thrombolysis, thrombectomy, craniotomy, embolization, stenting",
        "Biomarker": "如：ADC, rCBF, rCBV, MTT, TTP, TMax, FA",
        "Pathology": "如：hemorrhage, infarction, thrombosis, embolus",
        "MolecularFeature": "较少见",
        "GeneticFeature": "较少见",
        "ClinicalFeature": "如：neurological deficit, hemiparesis, aphasia, functional outcome",
        "Symptom": "如：headache, weakness, facial droop, speech difficulty, visual loss",
        "RiskFactor": "如：hypertension, diabetes, smoking, atrial fibrillation, age, hyperlipidemia",
        "Complication": "如：hemorrhagic transformation, mass effect, herniation, recurrent stroke",
        "StudyPopulation": "如：120 patients with acute ischemic stroke",
        "ImagingModality": "如：MRI, CT, MRA, CTA, DSA",
        "ContrastAgent": "如：gadolinium, Gd-DTPA",
        "Other": "如：NIHSS, mRS, GCS, ICH score, Hunt-Hess",
    },
    high_freq_entities="""### ⚠ 高频遗漏清单（脑血管疾病）

1. **Disease → HAS_RISK_FACTOR → RiskFactor**：卒中的危险因素（hypertension, diabetes, AF, smoking）
2. **Disease → HAS_FINDING → ImagingFinding**：卒中有什么影像表现？（infarct, penumbra, hematoma, restricted diffusion）
3. **ImagingFinding → VISIBLE_ON → MRISequence**：影像表现在哪个序列？（restricted diffusion on DWI, hematoma on SWI, penumbra on PWI）
4. **ImagingFinding → LOCATED_IN → Anatomy**：病灶位于哪个血管供血区/脑区？
5. **Disease → DIAGNOSED_BY → ImagingModality/MRISequence**：DWI诊断急性缺血性卒中
6. **Disease → ASSESSED_BY → Other(量表)**：NIHSS/mRS/GCS评估卒中严重度和预后
7. **Disease → TREATED_BY → Treatment**：溶栓/取栓/手术
8. **Disease → HAS_SYMPTOM → Symptom**：头痛/偏瘫/失语""",
    relation_patterns="""### 关系发现模式（脑血管疾病）

**临床论文**：
- "X is a risk factor for Y" → Y(Disease) HAS_RISK_FACTOR X(RiskFactor)
- "X was located in the Y territory" → X(ImagingFinding) LOCATED_IN Y(Anatomy)
- "DWI showed restricted diffusion in X" → X(ImagingFinding) VISIBLE_ON DWI
- "Patients with X had symptom Y" → X(Disease) HAS_SYMPTOM Y(Symptom: aphasia/hemiparesis)
- "X was diagnosed by DWI" → X(Disease) DIAGNOSED_BY DWI(MRISequence)
- "NIHSS score was X" → Disease ASSESSED_BY NIHSS(Other)
- "X was treated with thrombolysis/thrombectomy" → X(Disease) TREATED_BY Y(Treatment)
- "mRS at 90 days was X" → Disease ASSESSED_BY mRS(Other)
- "X is associated with Y" → X ASSOCIATED_WITH Y

**方法学论文**：
- "X was observed on Y" → X(ImagingFinding) VISIBLE_ON Y(MRISequence)
- "X showed higher sensitivity than Y" → X COMPARED_WITH Y (Comparative)
- "ADC values were lower in patients with X" → X(Disease) ASSOCIATED_WITH ADC(Biomarker) (Negative)
- "X is a marker of Y" → X(Biomarker) ASSOCIATED_WITH Y(Disease)
- "PWI/DWI mismatch identified penumbra" → penumbra(ImagingFinding) VISIBLE_ON PWI

**综述/指南论文**：
- "X is a risk factor for Y" → Y(Disease) HAS_RISK_FACTOR X(RiskFactor)
- "X predicts Y" → X PREDICTS Y
- "X is associated with Y" → X ASSOCIATED_WITH Y""",
    classification_hints="""### 判型提示（脑血管疾病）

- "penumbra" / "infarct core" / "hematoma" / "microbleeds" → ImagingFinding
- "restricted diffusion" → ImagingFinding
- "blooming artifact" → ImagingFinding
- "mass effect" / "midline shift" → ImagingFinding
- "vasospasm" → 视语境判 Disease（独立疾病）或 Complication（SAH的并发症）
- "atrial fibrillation" → RiskFactor（卒中语境下）；但作为心脏疾病诊断时 → Disease
- "carotid stenosis" → Disease（若作为卒中病因）或 RiskFactor（若作为危险因素描述）
- "neurological deficit" / "hemiparesis" / "aphasia" → ClinicalFeature 或 Symptom（视语境）
- "hemorrhage" → ImagingFinding（影像表现）/ Pathology（病理结果）/ Complication（治疗并发症）
- "NIHSS" / "mRS" / "GCS" → Other（评估量表）""",
    assessment_scales="""### 评估量表（脑血管疾病）

- NIHSS (National Institutes of Health Stroke Scale) → Other，作 ASSESSED_BY tail
- mRS (modified Rankin Scale) → Other
- GCS (Glasgow Coma Scale) → Other
- ICH score → Other
- Hunt-Hess scale → Other（SAH 专用）
- "NIHSS score was 12" → Disease ASSESSED_BY NIHSS
- "mRS ≤2 at 90 days" → Disease ASSESSED_BY mRS
- 量表 carve-out：方法句 "Patients were assessed with NIHSS" 照常建边""",
    example_output="""### 完整示例（脑血管疾病）

```json
{
  "document_id": "CV000075",
  "entities": [
    {"entity_type": "Disease", "mention": "acute ischemic stroke", "source_text": "Patients with acute ischemic stroke were treated with intravenous thrombolysis within 4.5 hours.", "page": 3, "section": "Methods"},
    {"entity_type": "RiskFactor", "mention": "hypertension", "source_text": "Hypertension was the most common risk factor in patients with acute ischemic stroke.", "page": 4, "section": "Results"},
    {"entity_type": "ImagingFinding", "mention": "restricted diffusion", "source_text": "DWI showed restricted diffusion in the MCA territory in 85% of patients.", "page": 5, "section": "Results"},
    {"entity_type": "MRISequence", "mention": "DWI", "source_text": "DWI showed restricted diffusion in the MCA territory in 85% of patients.", "page": 5, "section": "Results"},
    {"entity_type": "Anatomy", "mention": "MCA territory", "source_text": "DWI showed restricted diffusion in the MCA territory in 85% of patients.", "page": 5, "section": "Results"},
    {"entity_type": "Treatment", "mention": "thrombolysis", "source_text": "Patients with acute ischemic stroke were treated with intravenous thrombolysis within 4.5 hours.", "page": 3, "section": "Methods"},
    {"entity_type": "Other", "mention": "NIHSS", "source_text": "NIHSS was assessed at admission and at 90-day follow-up.", "page": 3, "section": "Methods"},
    {"entity_type": "StudyPopulation", "mention": "120 patients", "source_text": "120 patients with acute ischemic stroke were enrolled in this prospective study.", "page": 3, "section": "Methods"}
  ],
  "relations": [
    {"head_mention": "acute ischemic stroke", "head_entity_type": "Disease", "relation_type": "HAS_RISK_FACTOR", "tail_mention": "hypertension", "tail_entity_type": "RiskFactor", "assertion_type": "Positive", "source_text": "Hypertension was the most common risk factor in patients with acute ischemic stroke.", "page": 4, "section": "Results"},
    {"head_mention": "acute ischemic stroke", "head_entity_type": "Disease", "relation_type": "HAS_FINDING", "tail_mention": "restricted diffusion", "tail_entity_type": "ImagingFinding", "assertion_type": "Positive", "source_text": "DWI showed restricted diffusion in the MCA territory in 85% of patients.", "page": 5, "section": "Results"},
    {"head_mention": "restricted diffusion", "head_entity_type": "ImagingFinding", "relation_type": "VISIBLE_ON", "tail_mention": "DWI", "tail_entity_type": "MRISequence", "assertion_type": "Positive", "source_text": "DWI showed restricted diffusion in the MCA territory in 85% of patients.", "page": 5, "section": "Results"},
    {"head_mention": "restricted diffusion", "head_entity_type": "ImagingFinding", "relation_type": "LOCATED_IN", "tail_mention": "MCA territory", "tail_entity_type": "Anatomy", "assertion_type": "Positive", "source_text": "DWI showed restricted diffusion in the MCA territory in 85% of patients.", "page": 5, "section": "Results"},
    {"head_mention": "acute ischemic stroke", "head_entity_type": "Disease", "relation_type": "TREATED_BY", "tail_mention": "thrombolysis", "tail_entity_type": "Treatment", "assertion_type": "Positive", "source_text": "Patients with acute ischemic stroke were treated with intravenous thrombolysis within 4.5 hours.", "page": 3, "section": "Methods"},
    {"head_mention": "acute ischemic stroke", "head_entity_type": "Disease", "relation_type": "ASSESSED_BY", "tail_mention": "NIHSS", "tail_entity_type": "Other", "assertion_type": "Positive", "source_text": "NIHSS was assessed at admission and at 90-day follow-up.", "page": 3, "section": "Methods"},
    {"head_mention": "acute ischemic stroke", "head_entity_type": "Disease", "relation_type": "DIAGNOSED_BY", "tail_mention": "DWI", "tail_entity_type": "MRISequence", "assertion_type": "Positive", "source_text": "DWI showed restricted diffusion in the MCA territory in 85% of patients.", "page": 5, "section": "Results"}
  ]
}
```""",
)


# --------------------------------------------------------------------------- #
# Profile 3: 神经内科疾病（NL）
# --------------------------------------------------------------------------- #
NL_PROFILE = DiseaseProfile(
    name="神经内科疾病",
    doc_id_prefixes=("NL",),
    entity_examples={
        "Disease": "如：Alzheimer's disease, Parkinson's disease, multiple sclerosis (MS), ALS, epilepsy, frontotemporal dementia (FTD)",
        "ImagingFinding": "如：atrophy, white matter lesion, hyperintensity, plaque, cortical thinning, ventricular enlargement, iron deposition",
        "MRISequence": "如：DTI, MRS, fMRI, volumetric T1, FLAIR, T2WI, SWI, DWI, ASL",
        "Anatomy": "如：hippocampus, entorhinal cortex, substantia nigra, caudate, putamen, corpus callosum, thalamus",
        "Treatment": "如：levodopa, donepezil, memantine, riluzole, antiepileptic drugs, deep brain stimulation",
        "Biomarker": "如：fractional anisotropy (FA), mean diffusivity (MD), ADC, brain volume, cortical thickness, NAA/Cr ratio",
        "Pathology": "如：Lewy body, neurofibrillary tangle, amyloid plaque, demyelination, axonal loss, neuronal loss",
        "MolecularFeature": "如：APOE epsilon4, CSF biomarkers (Aβ42, tau)",
        "GeneticFeature": "如：APP mutation, PSEN1 mutation, LRRK2 mutation, CAG repeat expansion",
        "ClinicalFeature": "如：cognitive decline, memory loss, motor deficit, executive dysfunction, gait disturbance",
        "Symptom": "如：tremor, rigidity, seizure, bradykinesia, pain, fatigue, sleep disturbance",
        "RiskFactor": "如：age, family history, head trauma, cardiovascular risk factors",
        "Complication": "如：falls, aspiration pneumonia, pressure ulcers",
        "StudyPopulation": "如：80 patients with mild cognitive impairment",
        "ImagingModality": "如：MRI, PET, SPECT, fMRI",
        "ContrastAgent": "如：gadolinium",
        "Other": "如：MMSE, MoCA, UPDRS, EDSS, ADL, CDR",
    },
    high_freq_entities="""### ⚠ 高频遗漏清单（神经内科疾病）

1. **Disease → HAS_FINDING → ImagingFinding**：疾病有什么影像表现？（atrophy in hippocampus, white matter lesions, plaques）
2. **ImagingFinding → VISIBLE_ON → MRISequence**：影像表现在哪个序列？（plaques on FLAIR, atrophy on volumetric T1, iron on SWI）
3. **Biomarker → CORRELATES_WITH → Other(量表)**：FA/ADC/brain volume 与认知量表评分的相关性
4. **Disease → ASSESSED_BY → Other(量表)**：MMSE/MoCA/UPDRS/EDSS 评估疾病严重度
5. **ImagingFinding → LOCATED_IN → Anatomy**：萎缩/病灶位于哪个脑区？
6. **Disease → ASSOCIATED_WITH → Biomarker**：FA降低与疾病的关联
7. **Disease → TREATED_BY → Treatment**：多巴胺/胆碱酯酶抑制剂/抗癫痫药
8. **Disease → HAS_SYMPTOM → Symptom**：震颤/强直/癫痫发作""",
    relation_patterns="""### 关系发现模式（神经内科疾病）

**临床论文**：
- "Patients with X showed Y on Z" → X(Disease) HAS_FINDING Y(ImagingFinding) + Y VISIBLE_ON Z(MRISequence)
- "X was located in Y" → X(ImagingFinding/Disease) LOCATED_IN Y(Anatomy)
- "FA was decreased in the X tract in patients with Y" → Y(Disease) ASSOCIATED_WITH FA(Biomarker) (Negative) + FA LOCATED_IN X(Anatomy)
- "Hippocampal atrophy was observed in patients with X" → X(Disease) HAS_FINDING atrophy + atrophy LOCATED_IN hippocampus
- "MMSE score correlated with X" → X(Biomarker) CORRELATES_WITH MMSE(Other)
- "X was treated with Y" → X(Disease) TREATED_BY Y(Treatment: levodopa/donepezil)
- "X had symptom Y" → X(Disease) HAS_SYMPTOM Y(Symptom: tremor/seizure)
- "X is associated with Y" → X ASSOCIATED_WITH Y

**方法学论文**：
- "X was observed on Y" → X(ImagingFinding) VISIBLE_ON Y(MRISequence)
- "X showed higher sensitivity than Y" → X COMPARED_WITH Y (Comparative)
- "FA values were lower in patients with X" → X(Disease) ASSOCIATED_WITH FA(Biomarker) (Negative)
- "X is a marker of Y" → X(Biomarker) ASSOCIATED_WITH Y(Disease)
- "Brain volume correlated with MMSE scores" → brain volume(Biomarker) CORRELATES_WITH MMSE(Other)
- "NAA/Cr ratio was reduced in the X" → X(Anatomy) ASSOCIATED_WITH NAA/Cr(Biomarker) (Negative)
- "X improved detection of Y" → X IMPROVES Y
- "X showed correlation with Y" → X CORRELATES_WITH Y

**综述/指南论文**：
- "X is commonly associated with Y" → X ASSOCIATED_WITH Y
- "X predicts Y" → X PREDICTS Y
- "X improves Y" → X IMPROVES Y""",
    classification_hints="""### 判型提示（神经内科疾病）

- "cognitive decline" / "motor deficit" / "executive dysfunction" → ClinicalFeature（非 Disease）
- "dementia" → Disease（作为诊断时）或 ClinicalFeature（作为其他疾病症状时）
- "FA" (fractional anisotropy) → Biomarker（非 ImagingFinding——定量测量值）
- "MD" (mean diffusivity) → Biomarker
- "ADC" → Biomarker
- "brain volume" / "hippocampal volume" / "cortical thickness" → Biomarker（定量测量值）
- "MS plaque" / "white matter lesion" / "atrophy" → ImagingFinding
- "Lewy body" / "neurofibrillary tangle" / "amyloid plaque" → Pathology
- "demyelination" / "axonal loss" / "neuronal loss" → Pathology
- "APOE epsilon4" → MolecularFeature
- "APP mutation" / "PSEN1 mutation" → GeneticFeature
- "NAA" / "NAA/Cr ratio" / "choline" → Biomarker（MRS 代谢物）
- "iron deposition" → ImagingFinding（SWI 观察到）
- "default mode network" → Anatomy（脑网络/脑区）
- "activation" → ImagingFinding（task-based fMRI 结果）
- "UPDRS" / "MMSE" / "MoCA" / "EDSS" / "ADL" / "CDR" → Other（评估量表）""",
    assessment_scales="""### 评估量表（神经内科疾病）

- MMSE (Mini-Mental State Examination) → Other，作 ASSESSED_BY tail
- MoCA (Montreal Cognitive Assessment) → Other
- UPDRS (Unified Parkinson's Disease Rating Scale) → Other
- EDSS (Expanded Disability Status Scale) → Other（MS 专用）
- ADL (Activities of Daily Living) → Other
- CDR (Clinical Dementia Rating) → Other
- "MMSE score was 24" → Disease ASSESSED_BY MMSE
- "FA correlated with UPDRS scores" → FA(Biomarker) CORRELATES_WITH UPDRS(Other)
- 量表 carve-out：方法句 "Cognitive function was assessed with MMSE and MoCA" 照常建边""",
    example_output="""### 完整示例（神经内科疾病）

```json
{
  "document_id": "NL000123",
  "entities": [
    {"entity_type": "Disease", "mention": "Alzheimer's disease", "source_text": "Patients with Alzheimer's disease showed hippocampal atrophy on volumetric T1 MRI.", "page": 4, "section": "Results"},
    {"entity_type": "ImagingFinding", "mention": "atrophy", "source_text": "Patients with Alzheimer's disease showed hippocampal atrophy on volumetric T1 MRI.", "page": 4, "section": "Results"},
    {"entity_type": "Anatomy", "mention": "hippocampus", "source_text": "Patients with Alzheimer's disease showed hippocampal atrophy on volumetric T1 MRI.", "page": 4, "section": "Results"},
    {"entity_type": "MRISequence", "mention": "DTI", "source_text": "DTI revealed decreased FA in the corpus callosum in patients with Alzheimer's disease.", "page": 5, "section": "Results"},
    {"entity_type": "Biomarker", "mention": "FA", "source_text": "DTI revealed decreased FA in the corpus callosum in patients with Alzheimer's disease.", "page": 5, "section": "Results"},
    {"entity_type": "ClinicalFeature", "mention": "cognitive decline", "source_text": "Cognitive decline was assessed using the MMSE in all patients.", "page": 3, "section": "Methods"},
    {"entity_type": "Other", "mention": "MMSE", "source_text": "Cognitive decline was assessed using the MMSE in all patients.", "page": 3, "section": "Methods"},
    {"entity_type": "Treatment", "mention": "donepezil", "source_text": "Patients with Alzheimer's disease were treated with donepezil 10 mg daily.", "page": 3, "section": "Methods"}
  ],
  "relations": [
    {"head_mention": "Alzheimer's disease", "head_entity_type": "Disease", "relation_type": "HAS_FINDING", "tail_mention": "atrophy", "tail_entity_type": "ImagingFinding", "assertion_type": "Positive", "source_text": "Patients with Alzheimer's disease showed hippocampal atrophy on volumetric T1 MRI.", "page": 4, "section": "Results"},
    {"head_mention": "atrophy", "head_entity_type": "ImagingFinding", "relation_type": "LOCATED_IN", "tail_mention": "hippocampus", "tail_entity_type": "Anatomy", "assertion_type": "Positive", "source_text": "Patients with Alzheimer's disease showed hippocampal atrophy on volumetric T1 MRI.", "page": 4, "section": "Results"},
    {"head_mention": "Alzheimer's disease", "head_entity_type": "Disease", "relation_type": "ASSOCIATED_WITH", "tail_mention": "FA", "tail_entity_type": "Biomarker", "assertion_type": "Negative", "source_text": "DTI revealed decreased FA in the corpus callosum in patients with Alzheimer's disease.", "page": 5, "section": "Results"},
    {"head_mention": "Alzheimer's disease", "head_entity_type": "Disease", "relation_type": "ASSESSED_BY", "tail_mention": "MMSE", "tail_entity_type": "Other", "assertion_type": "Positive", "source_text": "Cognitive decline was assessed using the MMSE in all patients.", "page": 3, "section": "Methods"},
    {"head_mention": "Alzheimer's disease", "head_entity_type": "Disease", "relation_type": "TREATED_BY", "tail_mention": "donepezil", "tail_entity_type": "Treatment", "assertion_type": "Positive", "source_text": "Patients with Alzheimer's disease were treated with donepezil 10 mg daily.", "page": 3, "section": "Methods"},
    {"head_mention": "FA", "head_entity_type": "Biomarker", "relation_type": "CORRELATES_WITH", "tail_mention": "MMSE", "tail_entity_type": "Other", "assertion_type": "Positive", "source_text": "FA values in the corpus callosum correlated with MMSE scores (r=0.62, p<0.001).", "page": 6, "section": "Results"}
  ]
}
```""",
)


# --------------------------------------------------------------------------- #
# Profile 4: 精神类疾病（PS）
# --------------------------------------------------------------------------- #
PS_PROFILE = DiseaseProfile(
    name="精神类疾病",
    doc_id_prefixes=("PS",),
    entity_examples={
        "Disease": "如：schizophrenia, depression, bipolar disorder, anxiety disorder, ADHD, OCD, autism spectrum disorder (ASD)",
        "ImagingFinding": "如：activation, deactivation, hyperactivity, hypoactivity, cortical thinning, ventricular enlargement",
        "MRISequence": "如：fMRI (task-based & resting-state), DTI, MRS, T1WI, T2WI, FLAIR, SWI",
        "Anatomy": "如：prefrontal cortex, DLPFC, ACC, amygdala, hippocampus, insula, caudate, putamen, thalamus",
        "Treatment": "如：antipsychotics (risperidone, olanzapine), SSRIs (fluoxetine), mood stabilizers (lithium), CBT",
        "Biomarker": "如：functional connectivity (FC), ALFF, fALFF, ReHo, gray matter volume, cortical thickness, glutamate, GABA",
        "Pathology": "较少见",
        "MolecularFeature": "较少见",
        "GeneticFeature": "如：DISC1, CACNA1C, BDNF polymorphism",
        "ClinicalFeature": "如：psychopathology, negative symptoms, positive symptoms, cognitive impairment, social dysfunction",
        "Symptom": "如：hallucination, delusion, anxiety, depressed mood, anhedonia, irritability, inattention, compulsion",
        "RiskFactor": "如：family history, obstetric complications, cannabis use, childhood trauma, urban upbringing",
        "Complication": "如：suicide, substance abuse, metabolic syndrome (medication-induced)",
        "StudyPopulation": "如：60 patients with first-episode schizophrenia",
        "ImagingModality": "如：MRI, fMRI, PET, SPECT",
        "ContrastAgent": "如：gadolinium",
        "Other": "如：PANSS, HAM-D, YMRS, ADHD-RS, Y-BOCS, BPRS, MADRS",
    },
    high_freq_entities="""### ⚠ 高频遗漏清单（精神类疾病）

1. **Disease → HAS_SYMPTOM → Symptom**：精神疾病有什么症状？（hallucination, delusion, depressed mood, anhedonia）
2. **Biomarker → CORRELATES_WITH → Other(量表)**：功能连接/ALFF/ReHo 与精神量表评分的相关性
3. **Disease → ASSESSED_BY → Other(量表)**：PANSS/HAM-D/YMRS 评估疾病严重度
4. **ImagingFinding → LOCATED_IN → Anatomy**：激活/低激活位于哪个脑区？
5. **Biomarker → LOCATED_IN → Anatomy**：功能连接/ALFF 在哪个脑区变化？
6. **Disease → ASSOCIATED_WITH → Biomarker**：疾病与脑功能指标的关联
7. **Disease → TREATED_BY → Treatment**：抗精神病药/SSRI/情绪稳定剂
8. **Disease → HAS_RISK_FACTOR → RiskFactor**：家族史/大麻使用/童年创伤""",
    relation_patterns="""### 关系发现模式（精神类疾病）

**临床论文**：
- "Patients with X showed decreased functional connectivity in Y" → X(Disease) ASSOCIATED_WITH Y(Biomarker: FC) (Negative) + Y LOCATED_IN [region]
- "PANSS score correlated with X" → X(Biomarker) CORRELATES_WITH PANSS(Other)
- "X showed increased ALFF in the Y" → Y(Anatomy) ASSOCIATED_WITH ALFF(Biomarker) + ALFF LOCATED_IN Y
- "X was treated with Y" → X(Disease) TREATED_BY Y(Treatment: antipsychotics/SSRIs)
- "X had hallucinations/delusions" → X(Disease) HAS_SYMPTOM Y(Symptom: hallucination/delusion)
- "X was assessed by PANSS" → Disease ASSESSED_BY PANSS(Other)
- "X is a risk factor for Y" → Y(Disease) HAS_RISK_FACTOR X(RiskFactor)
- "Functional connectivity between X and Y was decreased" → X(Anatomy) ASSOCIATED_WITH Y(Anatomy) (Negative)

**方法学论文**：
- "X was observed on Y" → X(ImagingFinding) VISIBLE_ON Y(MRISequence)
- "X showed higher sensitivity than Y" → X COMPARED_WITH Y (Comparative)
- "FC was decreased in the X in patients with Y" → Y(Disease) ASSOCIATED_WITH FC(Biomarker) (Negative) + FC LOCATED_IN X(Anatomy)
- "ALFF in the X was higher in patients with Y" → Y(Disease) ASSOCIATED_WITH ALFF(Biomarker) + ALFF LOCATED_IN X(Anatomy)
- "PANSS positive score correlated with X" → X(Biomarker) CORRELATES_WITH PANSS(Other)
- "X improved detection of Y" → X IMPROVES Y
- "X outperformed Y" → X COMPARED_WITH Y (Comparative)

**综述/指南论文**：
- "X is commonly associated with Y" → X ASSOCIATED_WITH Y
- "X predicts Y" → X PREDICTS Y
- "X is a risk factor for Y" → Y(Disease) HAS_RISK_FACTOR X(RiskFactor)""",
    classification_hints="""### 判型提示（精神类疾病）

- "functional connectivity" (FC) → Biomarker（非 ImagingFinding——定量测量值）
- "ALFF" / "fALFF" / "ReHo" → Biomarker（fMRI 定量指标）
- "gray matter volume" / "cortical thickness" → Biomarker（定量测量值）
- "default mode network" (DMN) → Anatomy（脑网络/脑区）
- "activation" / "deactivation" → ImagingFinding（task-based fMRI 结果）
- "hyperactivity" / "hypoactivity" → ImagingFinding
- "psychopathology" / "negative symptoms" / "positive symptoms" → ClinicalFeature
- "cognitive impairment" / "social dysfunction" / "functional decline" → ClinicalFeature
- "hallucination" / "delusion" / "anxiety" / "depressed mood" / "anhedonia" → Symptom
- "schizophrenia" / "depression" / "bipolar disorder" → Disease（作为诊断时）
- "depression" → Disease（MDD 诊断）或 Symptom（其他疾病症状时）
- "family history" → RiskFactor
- "cannabis use" / "substance use" → RiskFactor
- "childhood trauma" / "obstetric complications" → RiskFactor
- "suicide" → Complication
- "PANSS" / "HAM-D" / "YMRS" / "ADHD-RS" / "Y-BOCS" / "BPRS" / "MADRS" → Other（评估量表）
- "glutamate" / "GABA" → Biomarker（MRS 神经递质）
- "BDNF polymorphism" / "DISC1" → GeneticFeature""",
    assessment_scales="""### 评估量表（精神类疾病）

- PANSS (Positive and Negative Syndrome Scale) → Other，作 ASSESSED_BY tail
- HAM-D / HDRS (Hamilton Depression Rating Scale) → Other
- YMRS (Young Mania Rating Scale) → Other
- ADHD-RS (ADHD Rating Scale) → Other
- Y-BOCS (Yale-Brown Obsessive Compulsive Scale) → Other
- BPRS (Brief Psychiatric Rating Scale) → Other
- MADRS (Montgomery-Asberg Depression Rating Scale) → Other
- "PANSS total score was 78" → Disease ASSESSED_BY PANSS
- "ALFF correlated with PANSS negative scores" → ALFF(Biomarker) CORRELATES_WITH PANSS(Other)
- 量表 carve-out：方法句 "Symptoms were assessed with PANSS" 照常建边""",
    example_output="""### 完整示例（精神类疾病）

```json
{
  "document_id": "PS000649",
  "entities": [
    {"entity_type": "Disease", "mention": "schizophrenia", "source_text": "Patients with schizophrenia showed decreased functional connectivity in the prefrontal cortex.", "page": 5, "section": "Results"},
    {"entity_type": "Biomarker", "mention": "functional connectivity", "source_text": "Patients with schizophrenia showed decreased functional connectivity in the prefrontal cortex.", "page": 5, "section": "Results"},
    {"entity_type": "Anatomy", "mention": "prefrontal cortex", "source_text": "Patients with schizophrenia showed decreased functional connectivity in the prefrontal cortex.", "page": 5, "section": "Results"},
    {"entity_type": "Symptom", "mention": "hallucination", "source_text": "Patients with schizophrenia experienced auditory hallucinations and delusions.", "page": 3, "section": "Methods"},
    {"entity_type": "ClinicalFeature", "mention": "negative symptoms", "source_text": "Negative symptoms were more severe in patients with chronic schizophrenia.", "page": 6, "section": "Results"},
    {"entity_type": "Other", "mention": "PANSS", "source_text": "PANSS was used to assess symptom severity at baseline and 12-week follow-up.", "page": 3, "section": "Methods"},
    {"entity_type": "Treatment", "mention": "risperidone", "source_text": "Patients with schizophrenia were treated with risperidone 4 mg daily.", "page": 3, "section": "Methods"},
    {"entity_type": "MRISequence", "mention": "fMRI", "source_text": "Resting-state fMRI revealed deactivation in the prefrontal cortex during the n-back task.", "page": 5, "section": "Results"},
    {"entity_type": "ImagingFinding", "mention": "deactivation", "source_text": "Resting-state fMRI revealed deactivation in the prefrontal cortex during the n-back task.", "page": 5, "section": "Results"}
  ],
  "relations": [
    {"head_mention": "schizophrenia", "head_entity_type": "Disease", "relation_type": "ASSOCIATED_WITH", "tail_mention": "functional connectivity", "tail_entity_type": "Biomarker", "assertion_type": "Negative", "source_text": "Patients with schizophrenia showed decreased functional connectivity in the prefrontal cortex.", "page": 5, "section": "Results"},
    {"head_mention": "functional connectivity", "head_entity_type": "Biomarker", "relation_type": "LOCATED_IN", "tail_mention": "prefrontal cortex", "tail_entity_type": "Anatomy", "assertion_type": "Positive", "source_text": "Patients with schizophrenia showed decreased functional connectivity in the prefrontal cortex.", "page": 5, "section": "Results"},
    {"head_mention": "schizophrenia", "head_entity_type": "Disease", "relation_type": "HAS_SYMPTOM", "tail_mention": "hallucination", "tail_entity_type": "Symptom", "assertion_type": "Positive", "source_text": "Patients with schizophrenia experienced auditory hallucinations and delusions.", "page": 3, "section": "Methods"},
    {"head_mention": "schizophrenia", "head_entity_type": "Disease", "relation_type": "ASSESSED_BY", "tail_mention": "PANSS", "tail_entity_type": "Other", "assertion_type": "Positive", "source_text": "PANSS was used to assess symptom severity at baseline and 12-week follow-up.", "page": 3, "section": "Methods"},
    {"head_mention": "schizophrenia", "head_entity_type": "Disease", "relation_type": "TREATED_BY", "tail_mention": "risperidone", "tail_entity_type": "Treatment", "assertion_type": "Positive", "source_text": "Patients with schizophrenia were treated with risperidone 4 mg daily.", "page": 3, "section": "Methods"},
    {"head_mention": "deactivation", "head_entity_type": "ImagingFinding", "relation_type": "VISIBLE_ON", "tail_mention": "fMRI", "tail_entity_type": "MRISequence", "assertion_type": "Positive", "source_text": "Resting-state fMRI revealed deactivation in the prefrontal cortex during the n-back task.", "page": 5, "section": "Results"},
    {"head_mention": "deactivation", "head_entity_type": "ImagingFinding", "relation_type": "LOCATED_IN", "tail_mention": "prefrontal cortex", "tail_entity_type": "Anatomy", "assertion_type": "Positive", "source_text": "Resting-state fMRI revealed deactivation in the prefrontal cortex during the n-back task.", "page": 5, "section": "Results"},
    {"head_mention": "schizophrenia", "head_entity_type": "Disease", "relation_type": "ASSOCIATED_WITH", "tail_mention": "negative symptoms", "tail_entity_type": "ClinicalFeature", "assertion_type": "Positive", "source_text": "Negative symptoms were more severe in patients with chronic schizophrenia.", "page": 6, "section": "Results"},
    {"head_mention": "functional connectivity", "head_entity_type": "Biomarker", "relation_type": "CORRELATES_WITH", "tail_mention": "PANSS", "tail_entity_type": "Other", "assertion_type": "Negative", "source_text": "Functional connectivity in the prefrontal cortex negatively correlated with PANSS negative scores (r=-0.45, p=0.003).", "page": 7, "section": "Results"}
  ]
}
```""",
)


# --------------------------------------------------------------------------- #
# 默认 Profile（序列/方法论文等无疾病系前缀的文献）
# --------------------------------------------------------------------------- #
DEFAULT_PROFILE = DiseaseProfile(
    name="通用",
    doc_id_prefixes=(),
    entity_examples=_DEFAULT_ENTITY_EXAMPLES,
)


# --------------------------------------------------------------------------- #
# 路由函数
# --------------------------------------------------------------------------- #
def select_profile(document_id: str) -> DiseaseProfile:
    """根据 document_id 前缀选择疾病系 profile。

    前缀映射：
        BT → 脑肿瘤
        CV → 脑血管疾病
        NL → 神经内科疾病
        PS → 精神类疾病
        其他 → DEFAULT_PROFILE（保留当前统一行为）

    参数：
        document_id  文献 ID，如 "BT000008"

    返回：
        DiseaseProfile 实例
    """
    if not document_id or len(document_id) < 2:
        return DEFAULT_PROFILE

    prefix = document_id[:2].upper()

    for profile in (BT_PROFILE, CV_PROFILE, NL_PROFILE, PS_PROFILE):
        if prefix in profile.doc_id_prefixes:
            return profile

    return DEFAULT_PROFILE


def merge_entity_examples(profile: DiseaseProfile) -> dict[str, str]:
    """合并 profile 专属示例与默认示例。

    profile.entity_examples 覆盖 _DEFAULT_ENTITY_EXAMPLES 的同名字段，
    缺失的 type 由默认兜底，确保 17 类 Entity 都有示例。
    """
    merged = dict(_DEFAULT_ENTITY_EXAMPLES)
    merged.update(profile.entity_examples)
    return merged
