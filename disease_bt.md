# disease_bt.md

# 脑肿瘤领域实体与关系抽取补充规则

## 1. 适用范围

本文件适用于脑肿瘤相关医学文献，包括脑肿瘤的 MRI 影像表现、影像定量分析、病理学特征、分子分型、遗传改变、治疗反应、预后及临床结局。

本文件只补充脑肿瘤领域的术语分类和抽取示例。实体类型、关系类型、断言类型、证据要求和 JSON 输出格式均遵循 `AGENT_INSTRUCTION.md`。

## 2. 常见实体及分类规则

### 2.1 Disease

常见疾病实体包括：

* glioblastoma
* astrocytoma
* oligodendroglioma
* meningioma
* medulloblastoma
* brain metastases
* pituitary adenoma
* diffuse glioma
* primary central nervous system lymphoma

具体抽取时以原文实际出现的疾病名称为准。不得根据影像表现自行推断肿瘤类型或分级。

### 2.2 ImagingFinding

常见影像征象包括：

* contrast enhancement
* peritumoral edema
* mass effect
* restricted diffusion
* necrotic appearance
* heterogeneous signal intensity
* T2/FLAIR hyperintensity
* susceptibility signal
* hemorrhagic component
* lesion heterogeneity

注意：

1. `necrosis` 若指 MRI 上观察到的坏死样区域或影像表现，归入 ImagingFinding。
2. `necrosis` 若指组织病理学坏死，归入 Pathology。
3. `edema` 若指影像观察到的水肿表现，可归入 ImagingFinding；若文献明确讨论其病理过程，应根据语境判断。
4. 不得仅因某种影像表现常见于某类肿瘤，就自动建立 Disease → HAS_FINDING → ImagingFinding。

### 2.3 MRISequence

常见序列包括：

* T1WI
* T2WI
* FLAIR
* DWI
* ADC map（若原文明确指 ADC 图像，可根据其语义归入相应成像对象；ADC 数值指标归入 Biomarker）
* SWI
* GRE
* DTI
* PWI
* ASL
* MR spectroscopy（若指具体成像或波谱技术，依据语义归入 MRISequence 或 ImagingModality）

不要将 ADC 数值和 ADC map 混为一谈。ADC 作为定量扩散指标时归入 Biomarker；ADC map 作为图像对象时按原文语义分类。

### 2.4 Anatomy

常见解剖实体包括：

* frontal lobe
* temporal lobe
* parietal lobe
* occipital lobe
* corpus callosum
* basal ganglia
* thalamus
* cerebellum
* brainstem
* hippocampus
* ventricular system

只有原文明确指出肿瘤或影像表现的位置时，才建立 LOCATED_IN 关系。

### 2.5 Biomarker

常见定量指标和生物标志物包括：

* ADC
* rCBV
* rCBF
* MTT
* FA
* MD
* Cho
* NAA
* NAA/Cr
* choline-to-NAA ratio
* Ki-67 labeling index

分类规则：

1. ADC、rCBV、FA 等影像定量指标归入 Biomarker。
2. Ki-67 若指增殖指数或标志物，归入 Biomarker。
3. 具体数值、升高、降低或比值变化不作为独立实体。
4. 如果原文报告某指标在不同肿瘤组之间存在差异，应按原文建立疾病与指标的关系，并在 relation 的 source_text 中保留差异描述。
5. 指标与疾病相关不意味着指标能够独立诊断疾病，不能将 ASSOCIATED_WITH_BIOMARKER 自动改成 DIAGNOSED_BY。

### 2.6 Pathology

常见病理实体包括：

* microvascular proliferation
* necrosis
* mitotic activity
* cellular atypia
* vascular proliferation
* neuronal loss（仅在原文确实涉及相关病理时使用）

必须根据原文语境区分影像征象与组织病理学特征。

例如：

* “MRI showed a necrotic core”中的 necrotic core 可按影像表现归入 ImagingFinding。
* “Histopathology demonstrated necrosis”中的 necrosis 应归入 Pathology。

### 2.7 MolecularFeature

常见分子特征包括：

* MGMT promoter methylation（当原文以分子特征或甲基化状态进行描述时）
* IDH-related molecular subtype（当原文强调分子亚型时）
* molecular subtype
* altered expression of a molecular marker（仅在原文明确指分子层面特征时）

分类规则：

1. 分子亚型、分子状态或分子层面的改变可归入 MolecularFeature。
2. 如果原文明确指基因突变、基因扩增、基因缺失或染色体改变，优先归入 GeneticFeature。
3. 同一具体概念应在全文中保持一致，不得在 MolecularFeature 和 GeneticFeature 之间随意切换。

### 2.8 GeneticFeature

常见遗传特征包括：

* IDH1 mutation
* IDH2 mutation
* EGFR amplification
* TP53 mutation
* BRAF V600E mutation
* TERT promoter mutation
* 1p/19q codeletion
* PTEN mutation

分类规则：

1. 明确的基因突变、扩增、缺失或染色体改变归入 GeneticFeature。
2. `IDH mutation` 若明确指 IDH 基因突变，归入 GeneticFeature。
3. 若原文讨论的是以 IDH 状态定义的分子亚型，而不是突变事件本身，可根据其语义归入 MolecularFeature。
4. `1p/19q codeletion` 归入 GeneticFeature。
5. 不得因为基因改变具有预后价值，就把它归为 Biomarker；只有在原文将其作为标志物进行明确讨论时，才考虑 Biomarker 分类，并须与全局定义保持一致。

### 2.9 Treatment

常见治疗实体包括：

* surgical resection
* radiotherapy
* chemotherapy
* temozolomide
* bevacizumab
* tumor-treating fields

只有在原文中确实承担治疗含义时，才建立 Disease → TREATED_BY → Treatment。

### 2.10 ClinicalFeature、Symptom 和 Other

ClinicalFeature 常见例子：

* tumor progression
* radiographic response
* cognitive decline
* functional outcome

Symptom 常见例子：

* headache
* seizure
* nausea
* visual disturbance
* weakness

Other 可用于明确的临床评分或量表，例如 KPS。

注意：

* KPS 作为量表或评分名称时归入 Other。
* WHO grade 通常是疾病的分级属性，不应自动作为独立实体抽取。
* 只有原文明确把某种分级或分型作为独立讨论对象，且现有实体类型能够合理表达时，才考虑抽取。
* 不要建立 WHO grade → HAS_PATHOLOGY 这类不符合语义或 Domain/Range 的关系。

## 3. 脑肿瘤领域常见关系模式

以下模式仅在原文存在直接证据时使用。

### 3.1 疾病与影像征象

Disease → HAS_FINDING → ImagingFinding

适用情形：文献明确指出某类肿瘤具有某种影像表现。

### 3.2 影像征象与序列

ImagingFinding → VISIBLE_ON → MRISequence

适用情形：文献明确指出某影像表现可在某 MRI 序列上观察到。

不能仅因为某序列被用于肿瘤检查，就建立 VISIBLE_ON。

### 3.3 影像征象与解剖位置

ImagingFinding → LOCATED_IN → Anatomy

适用情形：文献明确指出某影像表现位于某脑区或解剖结构。

如果原文描述的是肿瘤病灶的位置，也可在证据明确时使用 Disease → LOCATED_IN → Anatomy。

### 3.4 疾病与影像定量指标

Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker

适用情形：文献明确报告某肿瘤与 ADC、rCBV、FA、NAA/Cr 等指标有关。

数值升高或降低应保留在关系证据中。除非原文明确否定关联，否则不得因为指标降低而使用 Negative。

### 3.5 疾病与分子特征

Disease → ASSOCIATED_WITH_MOLECULAR_FEATURE → MolecularFeature

适用情形：文献明确报告某肿瘤与某分子特征或分子亚型相关。

### 3.6 疾病与遗传特征

Disease → ASSOCIATED_WITH_GENETIC_FEATURE → GeneticFeature

适用情形：文献明确报告某肿瘤与某遗传改变有关。

### 3.7 疾病与病理特征

Disease → HAS_PATHOLOGY → Pathology

适用情形：文献明确报告某肿瘤具有某种组织病理学特征。

### 3.8 疾病与治疗

Disease → TREATED_BY → Treatment

适用情形：文献明确指出某治疗用于该疾病。

### 3.9 疾病与量表

Disease 或 ClinicalFeature → ASSESSED_BY → Other

适用情形：文献明确指出 KPS 或其他量表用于评估肿瘤患者的功能状态或临床状态。

必须明确量表评估的对象，不能仅凭量表和疾病同时出现就建立关系。

## 4. 脑肿瘤领域的关系抽取限制

1. 不得将 WHO grade 自动识别为 Pathology。
2. 不得把影像上的坏死样表现与组织病理坏死混为一谈。
3. 不得将 IDH 突变、MGMT 甲基化、1p/19q 共缺失等术语随意分配到不同实体类型。
4. 不得根据肿瘤常见影像表现推断原文没有明确描述的 HAS_FINDING 关系。
5. 不得因为某分子特征具有诊断或预后价值，就自动建立 DIAGNOSED_BY 或 PREDICTS。
6. 只有原文明示预测意义时，才能使用 PREDICTS。
7. 不得将数值降低自动判定为 Negative。
8. 不得将同一关系的不同写法重复输出。
9. 所有关系必须符合 `AGENT_INSTRUCTION.md` 的 Domain/Range 约束。
10. 如果原文信息无法由现有实体和关系类型准确表达，应保留可确认的实体，不要强行生成关系。

## 5. 示例

以下为结构示例，仅用于说明抽取方式，不可直接作为真实文献的抽取结果。

原文：

“Glioblastoma showed restricted diffusion on DWI.”

可抽取实体：

* Disease：`Glioblastoma`
* ImagingFinding：`restricted diffusion`
* MRISequence：`DWI`

可抽取关系：

* Glioblastoma → HAS_FINDING → restricted diffusion
* restricted diffusion → VISIBLE_ON → DWI

每条关系的 source_text 必须使用能够直接支持该关系的原文。实际抽取时，实体 mention、大小写、page 和 section 均以输入文献为准。

原文：

“ADC values were lower in glioblastoma than in the comparison group.”

可在证据充分时抽取：

* Disease：`glioblastoma`
* Biomarker：`ADC`

关系：

* glioblastoma → ASSOCIATED_WITH_BIOMARKER → ADC

assertion_type：

* `Comparative`

不得仅因为 ADC 数值降低就将断言标记为 Negative。

## 6. 输出前检查

完成抽取后，额外检查：

1. 所有肿瘤相关实体是否按实际语义分类。
2. IDH mutation、MGMT promoter methylation、1p/19q codeletion 等是否遵循统一分类标准。
3. WHO grade 是否被错误地作为 Pathology 实体。
4. necrosis 等词是否依据影像或病理语境进行分类。
5. ADC、rCBV、FA、NAA/Cr 等是否被正确归入 Biomarker。
6. 是否错误地把定量变化解释为 Negative。
7. 每条关系是否符合全局 Domain/Range。
8. 每条关系是否有包含头尾实体的直接证据。

输出结构、字段和路径必须遵循 `AGENT_INSTRUCTION.md`。
