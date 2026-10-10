# disease_nl.md

# 神经内科疾病领域实体与关系抽取补充规则

## 1. 适用范围

本文件适用于神经内科疾病相关医学文献，包括神经退行性疾病、脱髓鞘疾病、癫痫、运动障碍、神经肌肉疾病及相关 MRI 影像表现、定量指标、病理特征、遗传特征、治疗和临床结局。

常见疾病包括阿尔茨海默病、帕金森病、多发性硬化、肌萎缩侧索硬化、癫痫、额颞叶痴呆和亨廷顿病等。

本文件只补充神经内科领域的术语分类及示例。所有实体、关系、断言类型、证据和 JSON 输出规则均遵循 `AGENT_INSTRUCTION.md`。

## 2. 常见实体及分类规则

### 2.1 Disease

常见疾病实体包括：

* Alzheimer's disease
* Parkinson's disease
* multiple sclerosis
* amyotrophic lateral sclerosis
* epilepsy
* frontotemporal dementia
* Huntington's disease
* mild cognitive impairment
* dementia with Lewy bodies

注意：

1. 疾病名称按原文抽取。
2. `dementia` 若明确作为疾病诊断使用，归入 Disease。
3. `cognitive impairment` 若指广义临床功能状态，可归入 ClinicalFeature；若原文明确将其作为特定诊断名称使用，应根据语境判断。
4. 不得仅凭认知下降、脑萎缩或其他影像表现推断具体神经系统疾病。

### 2.2 ImagingFinding

常见影像征象包括：

* brain atrophy
* hippocampal atrophy
* cortical thinning
* ventricular enlargement
* white matter lesions
* white matter hyperintensities
* demyelinating plaques
* iron deposition
* regional volume loss
* lesion burden

分类规则：

1. 影像上观察到的脑萎缩、皮层变薄、脑室扩大和白质高信号等归入 ImagingFinding。
2. `demyelinating plaques` 若作为 MRI 上的病灶或影像征象使用，可归入 ImagingFinding。
3. 若原文明确讨论组织病理学脱髓鞘，则归入 Pathology。
4. `atrophy` 和 `hippocampal atrophy` 应根据原文完整表达抽取，不得擅自把复合 mention 缩短。
5. 不得仅凭某种影像征象在某疾病中常见，就自动建立 HAS_FINDING。

### 2.3 MRISequence 和 ImagingModality

常见 MRISequence 包括：

* T1-weighted imaging
* T2WI
* FLAIR
* DWI
* SWI
* DTI
* ASL
* MR spectroscopy

常见 ImagingModality 包括：

* MRI
* fMRI
* MRA
* PET
* CT

分类规则：

1. 具体 MRI 序列归入 MRISequence。
2. fMRI 若表示功能磁共振成像方式，归入 ImagingModality。
3. DTI 若在原文中指具体扩散张量成像技术或序列，按其语义归入 MRISequence；若明确作为成像模态使用，则归入 ImagingModality。
4. 不得仅根据术语缩写判断类型，必须结合原文语境。
5. “通过 DTI 分析白质微结构”不自动意味着每个白质异常都 VISIBLE_ON DTI；只有原文明确说明其可见性时才建立 VISIBLE_ON。

### 2.4 Anatomy

常见解剖实体包括：

* hippocampus
* amygdala
* thalamus
* basal ganglia
* corpus callosum
* prefrontal cortex
* motor cortex
* cerebellum
* brainstem
* substantia nigra
* white matter tracts

分类规则：

1. 只有明确的解剖结构或脑区才能归入 Anatomy。
2. `white matter tract` 可作为 Anatomy；`white matter integrity` 通常不是解剖结构，应根据语境考虑 Biomarker 或 ClinicalFeature。
3. `functional connectivity` 不是 Anatomy。
4. 若文献只报告某个指标在某脑区降低，但当前关系 Schema 无法准确表示该指标在该脑区的测量关系，不得强行使用 LOCATED_IN。

### 2.5 Biomarker

常见定量指标包括：

* FA
* MD
* ADC
* brain volume
* cortical thickness
* NAA/Cr
* choline/Cr
* functional connectivity
* ALFF
* fALFF
* ReHo
* regional cerebral blood flow

分类规则：

1. 明确的影像定量指标归入 Biomarker。
2. FA、MD、ADC 等指标的升高或降低不是独立实体。
3. `functional connectivity`、ALFF、fALFF、ReHo 等作为定量影像指标时归入 Biomarker。
4. 脑体积、皮层厚度等作为定量测量指标时归入 Biomarker；如果原文描述的是“脑萎缩”这一影像征象，则归入 ImagingFinding。
5. 不得仅因为指标在某脑区测量，就建立 Biomarker → LOCATED_IN → Anatomy。当前全局 LOCATED_IN 不允许 Biomarker 作为头实体。
6. 若原文明确报告疾病与某定量指标相关或存在组间差异，可根据语义建立 Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker。

### 2.6 Pathology

常见病理实体包括：

* neuronal loss
* demyelination
* amyloid plaques
* neurofibrillary tangles
* Lewy bodies
* axonal loss

分类规则：

1. 只有原文明确讨论病理组织学或病理过程时才归入 Pathology。
2. MRI 上观察到的白质病灶或皮层变薄应归入 ImagingFinding，而不是自动归入 Pathology。
3. 影像表现与组织病理改变之间的对应关系必须有原文证据，不能凭医学常识推断。

### 2.7 MolecularFeature 和 GeneticFeature

常见 MolecularFeature 包括：

* amyloid-related molecular abnormality
* tau-related molecular abnormality
* altered molecular expression（原文明确涉及分子层面时）

常见 GeneticFeature 包括：

* APOE ε4 allele
* APP mutation
* PSEN1 mutation
* LRRK2 mutation
* CAG repeat expansion

分类规则：

1. 明确的基因变异、突变、重复扩增或遗传等位基因归入 GeneticFeature。
2. 分子层面的状态或分子亚型可归入 MolecularFeature。
3. CSF Aβ42、tau 等术语应依据文献语境判断：若作为生物标志物测量值使用，归入 Biomarker；若明确指分子特征本身，则可归入 MolecularFeature。
4. 不得仅因某遗传特征与疾病有关，就自动建立 PREDICTS。
5. 具体遗传特征与疾病之间的关系应优先使用 ASSOCIATED_WITH_GENETIC_FEATURE。

### 2.8 Treatment

常见治疗实体包括：

* levodopa
* donepezil
* memantine
* riluzole
* antiseizure medication
* deep brain stimulation

只有文献明确说明治疗对象和治疗含义时，才建立 TREATED_BY。

如果深部脑刺激仅作为研究或实验干预使用，应根据原文实际语义判断是否属于 Treatment。

### 2.9 ClinicalFeature、Symptom 和 Other

ClinicalFeature 常见例子：

* cognitive decline
* memory impairment
* executive dysfunction
* motor dysfunction
* gait disturbance
* functional decline

Symptom 常见例子：

* tremor
* rigidity
* bradykinesia
* seizure
* fatigue
* pain
* sleep disturbance

Other 常见例子：

* MMSE
* MoCA
* UPDRS
* EDSS
* ADL
* CDR

分类规则：

1. MMSE、MoCA、UPDRS、EDSS 等作为量表或评分名称时归入 Other。
2. `memory impairment`、`executive dysfunction` 等按其在原文中是症状还是总体临床特征，分别归入 Symptom 或 ClinicalFeature；同一语境下应保持一致。
3. 只有原文明示量表用于评估某对象时，才建立 ASSESSED_BY。
4. 不得仅因量表与疾病在同一句中出现就推断评估关系。

## 3. 神经内科领域常见关系模式

### 3.1 疾病与影像表现

Disease → HAS_FINDING → ImagingFinding

只有原文明确指出某疾病具有某种影像表现时才使用。

### 3.2 影像表现与序列

ImagingFinding → VISIBLE_ON → MRISequence

只有原文明示某影像表现可在某序列上观察到时才使用。

### 3.3 影像表现与解剖结构

ImagingFinding → LOCATED_IN → Anatomy

适用于原文明确指出脑萎缩、病灶或其他影像表现位于某脑区的情况。

### 3.4 疾病与定量指标

Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker

适用于原文明确报告疾病与 FA、MD、ADC、脑体积、皮层厚度、功能连接等指标存在关联或差异的情况。

如果原文报告的是组间差异，应优先使用 Comparative 断言类型。

### 3.5 疾病与遗传特征

Disease → ASSOCIATED_WITH_GENETIC_FEATURE → GeneticFeature

适用于原文明确报告某疾病与特定遗传变异或遗传特征相关的情况。

### 3.6 疾病与分子特征

Disease → ASSOCIATED_WITH_MOLECULAR_FEATURE → MolecularFeature

适用于原文明确报告某疾病与分子状态或分子亚型有关的情况。

### 3.7 疾病与病理

Disease → HAS_PATHOLOGY → Pathology

适用于原文明确指出某疾病具有某种病理学改变的情况。

### 3.8 疾病与治疗

Disease → TREATED_BY → Treatment

适用于原文明确说明某治疗用于该疾病的情况。

### 3.9 疾病或临床特征与量表

Disease 或 ClinicalFeature → ASSESSED_BY → Other

只有原文明确说明量表评估对象时才使用。

## 4. 神经内科领域的特别限制

1. 不得将脑萎缩、白质高信号等影像征象自动分类为 Pathology。
2. 不得把 FA、MD、ADC、ALFF、ReHo 等指标的降低自动标记为 Negative。
3. 不得因为指标在某脑区测量，就建立不符合全局 Domain/Range 的 Biomarker → LOCATED_IN → Anatomy。
4. 不得把功能连接降低简化为两个脑区之间的普通 ASSOCIATED_WITH 关系；这种简化会丢失“功能连接”这一关键语义。
5. 如果原文报告脑区 A 与脑区 B 之间的功能连接降低，但当前 Schema 没有可表达该连接及其方向的关系类型，则不抽取该脑区到脑区的关系。若文中另外明确报告疾病与 functional connectivity 指标的关联，可独立抽取该关系。
6. 不得将量表名称误分类为疾病或临床症状。
7. 不得把“指标降低”直接解释为疾病加重、功能恶化或 Negative；必须有原文证据支持相应方向。
8. 不得仅根据已知医学关联推断疾病、病理、分子或遗传关系。
9. 所有关系必须符合 `AGENT_INSTRUCTION.md` 的 Domain/Range 和证据规范。

## 5. 示例

以下仅用于说明抽取方式，不可直接作为真实文献的抽取结果。

原文：

“Patients with Alzheimer's disease showed hippocampal atrophy on volumetric T1-weighted imaging.”

实体：

* Disease：`Alzheimer's disease`
* ImagingFinding：`hippocampal atrophy`
* Anatomy：`hippocampus`（只有原文明确出现该独立 mention，且有必要单独抽取时才建立独立实体）
* MRISequence：`volumetric T1-weighted imaging`

关系：

* Alzheimer's disease → HAS_FINDING → hippocampal atrophy
* hippocampal atrophy → VISIBLE_ON → volumetric T1-weighted imaging
* hippocampal atrophy → LOCATED_IN → hippocampus（仅当原文明确支持该关系且 `hippocampus` 是原文中的独立 mention 时）

实际抽取时，不得为了生成 LOCATED_IN 而把 `hippocampal atrophy` 拆分或改写成原文不存在的实体。

原文：

“FA values were lower in patients with multiple sclerosis than in healthy controls.”

实体：

* Disease：`multiple sclerosis`
* Biomarker：`FA`

关系：

* multiple sclerosis → ASSOCIATED_WITH_BIOMARKER → FA

断言类型：

* `Comparative`

不得仅因 FA 数值较低就标记 Negative，也不得在没有明确证据的情况下补充具体白质束或脑区。

原文：

“Lower FA values were associated with poorer performance on the MoCA.”

实体：

* Biomarker：`FA`
* Other：`MoCA`
* ClinicalFeature：只有原文明确提及并支持时才抽取对应的认知表现特征

不能仅凭这句话强行建立 FA → ASSESSED_BY → MoCA；必须明确 MoCA 的评估对象，且关系方向和含义要符合全局定义。

## 6. 输出前检查

1. 是否区分影像表现与病理特征。
2. 是否按语境区分 MRISequence 与 ImagingModality。
3. 是否将 FA、MD、ADC、ALFF、ReHo、functional connectivity 等定量指标归入 Biomarker。
4. 是否避免 Biomarker → LOCATED_IN → Anatomy 这种不符合当前 Schema 的关系。
5. 是否避免将脑区之间的功能连接简化成普通脑区关联。
6. 是否避免将数值降低自动标记为 Negative。
7. 是否正确处理量表名称及其评估对象。
8. 每条关系是否有直接证据并符合全局 Domain/Range。

输出结构、字段和路径必须遵循 `AGENT_INSTRUCTION.md`。
