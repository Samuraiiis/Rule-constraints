# disease_cv.md

# 脑血管疾病领域实体与关系抽取补充规则

## 1. 适用范围

本文件适用于脑血管疾病相关医学文献，包括缺血性卒中、脑出血、蛛网膜下腔出血、脑动脉瘤、脑血管畸形、血管狭窄、脑灌注异常、脑小血管病及相关 MRI 影像表现、定量指标、危险因素、治疗和临床结局。

本文件只补充脑血管领域的术语分类和抽取示例。所有实体、关系、断言类型、证据和 JSON 输出规则均遵循 `AGENT_INSTRUCTION.md`。

## 2. 常见实体及分类规则

### 2.1 Disease

常见疾病或诊断实体包括：

* acute ischemic stroke
* intracerebral hemorrhage
* subarachnoid hemorrhage
* cerebral aneurysm
* arteriovenous malformation
* carotid artery stenosis
* cerebral small vessel disease
* cerebral venous sinus thrombosis
* transient ischemic attack
* cerebral vasospasm

注意：

1. `ischemic stroke`、`intracerebral hemorrhage` 等作为疾病诊断时归入 Disease。
2. `carotid artery stenosis` 若指明确诊断或疾病状态，可归入 Disease；若原文只是描述某个血管的狭窄影像征象，应根据语境判断是否归入 ImagingFinding。
3. `thrombosis` 若指明确的血栓性疾病或诊断，可归入 Disease；若仅指病理过程，可归入 Pathology。
4. `infarction` 若作为临床诊断或疾病过程使用，可归入 Disease 或 Pathology，具体取决于原文语义；若指 MRI 上的梗死灶或影像表现，应归入 ImagingFinding。
5. 不得仅凭影像征象推断原文未明确诊断的疾病。

### 2.2 ImagingFinding

常见影像征象包括：

* restricted diffusion
* diffusion-weighted hyperintensity
* infarct lesion
* ischemic penumbra（若作为影像评估识别的区域或影像相关概念使用）
* hematoma
* hemorrhagic transformation
* microbleeds
* blooming artifact
* mass effect
* white matter hyperintensity
* perfusion deficit
* arterial occlusion sign

分类规则：

1. `hematoma` 若指影像上观察到的血肿，归入 ImagingFinding；若指病理或疾病过程，依据语境判断。
2. `hemorrhagic transformation` 若指影像观察到的出血性转化，可归入 ImagingFinding；若原文明确讨论其并发症性质，也可按 Complication 处理，但同一处语境应保持一致。
3. `infarct` 若指 MRI 上观察到的梗死灶，可归入 ImagingFinding。
4. `ischemic penumbra` 不应仅因它由灌注或弥散不匹配识别，就自动建立 VISIBLE_ON 与单一序列的关系。
5. `mass effect` 若作为影像表现使用，归入 ImagingFinding；只有明确作为并发症讨论时，才考虑 Complication。
6. 不能仅因某影像征象常见于某疾病，就自动建立 HAS_FINDING。

### 2.3 MRISequence 和 ImagingModality

常见 MRISequence 包括：

* DWI
* FLAIR
* T2WI
* SWI
* GRE
* PWI
* ASL
* DTI

常见 ImagingModality 包括：

* MRI
* MRA
* MR angiography（作为血管成像方式使用时）
* CTA
* CT
* PET

分类规则：

1. DWI、FLAIR、SWI、PWI、ASL 等具体 MRI 序列或序列技术，归入 MRISequence。
2. MRA 若表示磁共振血管成像方式，归入 ImagingModality。
3. 如果原文将某一术语用作具体序列名称，应依据其实际语义分类，不得只按缩写机械判断。
4. 不能因为某序列用于脑血管检查，就自动建立 DIAGNOSED_BY。
5. 如果原文明确表示某疾病通过 DWI 诊断或识别，可建立 Disease → DIAGNOSED_BY → DWI。
6. 如果原文明确指出某征象在 DWI 上可见，才建立 ImagingFinding → VISIBLE_ON → DWI。

### 2.4 Anatomy

常见解剖实体包括：

* middle cerebral artery
* anterior cerebral artery
* posterior cerebral artery
* internal carotid artery
* basilar artery
* vertebral artery
* thalamus
* basal ganglia
* brainstem
* cerebellum
* hippocampus
* periventricular white matter

注意：

* 血管名称归入 Anatomy。
* 若原文讨论某血管的狭窄、闭塞或动脉瘤，应将血管本身与其病变概念区分。
* 只有原文明确指出病灶、影像征象或病理改变的位置时，才建立 LOCATED_IN。

### 2.5 Biomarker

常见影像定量指标包括：

* ADC
* rCBF
* rCBV
* MTT
* TTP
* Tmax
* FA
* MD

分类规则：

1. ADC、rCBF、rCBV、MTT、TTP、Tmax 等定量指标归入 Biomarker。
2. FA、MD 等扩散相关指标归入 Biomarker。
3. 指标的具体数值、升高、降低或差异描述不作为独立实体。
4. 若原文报告某指标在不同患者组或病灶区域之间存在差异，可根据证据建立 Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker。
5. 若原文仅报告组间数值差异，断言类型优先使用 Comparative。
6. 指标降低不代表关系被否定，不能仅据此使用 Negative。
7. 只有原文明示该指标用于预测结局时，才建立 PREDICTS。

### 2.6 Pathology

常见病理过程包括：

* infarction
* hemorrhage
* thrombosis
* embolism
* ischemic injury

分类规则：

1. 必须根据原文判断术语是否指病理过程。
2. 如果 `hemorrhage` 指 MRI 上观察到的出血征象，应归入 ImagingFinding。
3. 如果 `hemorrhage` 指明确的病理过程或病理状态，可归入 Pathology。
4. 如果 `infarction` 指临床诊断或影像梗死灶，不应机械地归入 Pathology。
5. 同一处语境中应保持分类一致。

### 2.7 Treatment

常见治疗实体包括：

* intravenous thrombolysis
* mechanical thrombectomy
* endovascular treatment
* aneurysm coiling
* surgical clipping
* hematoma evacuation
* antithrombotic therapy
* carotid artery stenting

只有文献明确指出某治疗用于某疾病时，才建立 TREATED_BY。

不能仅因为某治疗是相关疾病的常规治疗，就自动建立关系。

### 2.8 ClinicalFeature、Symptom、RiskFactor、Complication 和 Other

ClinicalFeature 常见例子：

* neurological deficit
* functional outcome
* level of consciousness
* disability
* cognitive impairment

Symptom 常见例子：

* headache
* weakness
* facial droop
* speech difficulty
* visual loss
* dizziness

RiskFactor 常见例子：

* hypertension
* diabetes
* smoking
* atrial fibrillation
* hyperlipidemia
* advanced age

Complication 常见例子：

* hemorrhagic transformation
* brain herniation
* recurrent stroke
* infection
* cerebral edema（只有明确作为并发症讨论时）

Other 常见例子：

* NIHSS
* mRS
* GCS
* ICH score
* Hunt-Hess scale

分类规则：

1. NIHSS、mRS、GCS 等作为量表或评分名称时归入 Other。
2. `atrial fibrillation` 若作为危险因素讨论，可归入 RiskFactor；若作为独立诊断讨论，可归入 Disease。
3. `hemorrhagic transformation` 应根据原文是影像表现还是并发症来决定分类。
4. 不得仅因为某评分与疾病同时出现，就自动建立 ASSESSED_BY。
5. 只有原文明确说明评分评估的对象时，才能建立 ASSESSED_BY。

## 3. 脑血管领域常见关系模式

### 3.1 疾病与影像表现

Disease → HAS_FINDING → ImagingFinding

只有文献明确指出某疾病具有某种影像表现时才使用。

### 3.2 影像表现与序列

ImagingFinding → VISIBLE_ON → MRISequence

只有文献明确指出某征象可在某序列上观察到时才使用。

“使用 DWI 诊断急性缺血性卒中”可以支持 DIAGNOSED_BY，但不自动支持某个特定影像征象的 VISIBLE_ON。

### 3.3 疾病与诊断方式

Disease → DIAGNOSED_BY → ImagingModality 或 MRISequence

只有原文明确表示某疾病通过某成像方式或序列进行诊断、识别时才使用。

### 3.4 影像表现与解剖结构

ImagingFinding → LOCATED_IN → Anatomy

适用于明确描述病灶位置、出血部位、梗死部位或其他影像表现所在区域的句子。

### 3.5 疾病与定量指标

Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker

适用于原文明确报告疾病与 ADC、rCBV、rCBF、MTT、Tmax 等指标存在关联、差异或定量关系的情形。

如果原文只报告组间差异，断言类型应使用 Comparative，而不是 Negative。

### 3.6 疾病与危险因素

Disease → HAS_RISK_FACTOR → RiskFactor

适用于原文明确将某因素描述为危险因素或易感因素的情形。

### 3.7 疾病与并发症

Disease → HAS_COMPLICATION → Complication

适用于原文明确指出某疾病可能出现或伴有某并发症的情形。

### 3.8 疾病与治疗

Disease → TREATED_BY → Treatment

适用于原文明确指出某治疗用于该疾病的情形。

### 3.9 疾病与量表

Disease 或 ClinicalFeature → ASSESSED_BY → Other

只有原文明确指出量表用于评估该疾病或临床特征时才使用。

## 4. 脑血管领域的特别限制

1. 不得将 MRA 一律分类为 MRISequence；需根据语义判断其是否为成像方式。
2. 不得把 ADC 数值降低自动标记为 Negative。
3. 不得将“通过 PWI/DWI mismatch 识别缺血半暗带”自动拆成缺血半暗带 VISIBLE_ON PWI 和 VISIBLE_ON DWI，除非原文分别明确支持这些可见性关系。
4. 不得将“指标与预后有关”自动解释为 PREDICTS。
5. 不得将血管解剖结构与其病变概念混为一谈。
6. 不得仅凭临床常识推断 HAS_RISK_FACTOR 或 TREATED_BY。
7. 不得将影像征象、病理过程、疾病诊断和并发症混为一谈。
8. 不得把 NIHSS、mRS、GCS 等评分名称当作疾病实体。
9. 每条关系必须符合 `AGENT_INSTRUCTION.md` 的 Domain/Range 约束。
10. 如果现有 Schema 无法准确表示某项影像评估事实，应保留可确认的实体，不要强行建立关系。

## 5. 示例

以下仅用于说明抽取方式，不可直接作为真实文献的抽取结果。

原文：

“Acute ischemic stroke was diagnosed by DWI in all cases.”

实体：

* Disease：`Acute ischemic stroke`
* MRISequence：`DWI`

关系：

* Acute ischemic stroke → DIAGNOSED_BY → DWI

断言类型：`Positive`

原文：

“ADC values were lower in patients with acute ischemic stroke than in controls.”

实体：

* Disease：`acute ischemic stroke`
* Biomarker：`ADC`

关系：

* acute ischemic stroke → ASSOCIATED_WITH_BIOMARKER → ADC

断言类型：`Comparative`

不得将该关系标记为 Negative，因为原文表达的是数值比较，而不是否定疾病与 ADC 的关联。

原文：

“Microbleeds were visible on SWI.”

实体：

* ImagingFinding：`Microbleeds`
* MRISequence：`SWI`

关系：

* Microbleeds → VISIBLE_ON → SWI

断言类型：`Positive`

实际抽取时必须使用原文中真实存在的 mention 和证据，不得复制示例内容。

## 6. 输出前检查

1. 是否根据语境正确区分 Disease、ImagingFinding、Pathology 和 Complication。
2. 是否正确区分 MRISequence 与 ImagingModality。
3. 是否将 ADC、rCBV、rCBF、MTT、Tmax 等定量指标归入 Biomarker。
4. 是否将量表名称归入 Other。
5. 是否错误地把数值降低解释为 Negative。
6. 是否把识别方式、可见性和诊断关系混为一谈。
7. 是否将血管解剖结构与血管病变区分开。
8. 所有关系是否符合 `AGENT_INSTRUCTION.md` 的 Domain/Range 和证据规范。

输出结构、字段和路径必须遵循 `AGENT_INSTRUCTION.md`。
