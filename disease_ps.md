# disease_ps.md

# 精神类疾病领域实体与关系抽取补充规则

## 1. 适用范围

本文件适用于精神类疾病相关医学文献，包括精神分裂症、抑郁障碍、双相障碍、焦虑障碍、注意缺陷多动障碍、强迫症、孤独症谱系障碍、创伤后应激障碍及相关 MRI 影像表现、功能连接、影像定量指标、遗传特征、临床表现、治疗和量表评估。

本文件只补充精神类疾病领域的术语分类及示例。所有实体、关系、断言类型、证据和 JSON 输出规则均遵循 `AGENT_INSTRUCTION.md`。

## 2. 常见实体及分类规则

### 2.1 Disease

常见疾病实体包括：

* schizophrenia
* major depressive disorder
* bipolar disorder
* anxiety disorder
* attention-deficit/hyperactivity disorder
* obsessive-compulsive disorder
* autism spectrum disorder
* post-traumatic stress disorder

注意：

1. 以原文明确的疾病诊断为准。
2. 不得根据影像表现、症状或量表分数自行推断疾病。
3. 同一疾病的诊断名称、亚型和症状表现应分别处理，不能把症状直接归为 Disease。

### 2.2 ImagingFinding

常见影像表现包括：

* regional hyperactivation
* regional hypoactivation
* increased activation
* decreased activation
* cortical thinning
* ventricular enlargement
* altered gray matter morphology
* regional volume reduction

分类规则：

1. 原文明确描述的脑区激活或失活现象，可以归入 ImagingFinding。
2. `cortical thinning`、`ventricular enlargement` 等形态学影像表现归入 ImagingFinding。
3. ALFF、fALFF、ReHo、functional connectivity 等定量指标归入 Biomarker，而不是 ImagingFinding。
4. “激活降低”与“功能连接降低”不是同一概念，不得相互替代。
5. 不得仅根据影像表现推断精神类疾病诊断。

### 2.3 MRISequence 和 ImagingModality

常见 MRISequence 包括：

* T1WI
* T2WI
* FLAIR
* DTI
* DWI
* SWI
* MR spectroscopy

常见 ImagingModality 包括：

* MRI
* fMRI
* MRA
* PET
* CT

分类规则：

1. fMRI 若作为功能磁共振成像方式使用，归入 ImagingModality。
2. DTI、DWI、FLAIR 等根据具体语义归入 MRISequence。
3. 如果原文把某术语用作具体序列或技术名称，应根据实际语境分类，不得只按缩写机械判断。
4. 不得仅因某研究采用 fMRI，就自动将所有脑区表现与 fMRI 建立 VISIBLE_ON 关系。
5. 只有原文明示某影像表现可在某序列上观察到时，才建立 VISIBLE_ON。

### 2.4 Anatomy

常见解剖实体包括：

* prefrontal cortex
* dorsolateral prefrontal cortex
* anterior cingulate cortex
* amygdala
* hippocampus
* insula
* thalamus
* basal ganglia
* cerebellum
* brainstem
* default mode network nodes（仅当原文明确将其作为解剖区域或节点讨论时，需谨慎判断）

分类规则：

1. 明确的脑区和解剖结构归入 Anatomy。
2. 功能连接、网络活动、脑区激活强度等指标不能归入 Anatomy。
3. `default mode network` 等网络名称不应一律视为单个解剖结构；应依据原文将其作为功能网络、研究对象还是解剖区域来判断。
4. 不得把两个脑区之间的功能连接直接转换成脑区 A 与脑区 B 的普通 ASSOCIATED_WITH 关系。

### 2.5 Biomarker

常见精神影像定量指标包括：

* functional connectivity
* ALFF
* fALFF
* ReHo
* gray matter volume
* cortical thickness
* FA
* MD
* glutamate
* GABA

分类规则：

1. 功能连接、局部一致性、低频振幅、灰质体积和皮层厚度等作为定量影像指标时归入 Biomarker。
2. FA、MD 等扩散指标归入 Biomarker。
3. 谷氨酸、GABA 等术语应根据语境判断：若作为生物化学测量指标使用，可归入 Biomarker；若原文强调其分子层面特征，则应依据全局分类规则判断。
4. 指标升高、降低或异常不作为独立实体。
5. 不得将功能连接指标归入 Anatomy。
6. 不得仅因为某指标在某脑区测量，就建立 Biomarker → LOCATED_IN → Anatomy；当前全局 Schema 不允许 Biomarker 作为 LOCATED_IN 的头实体。
7. 如果原文明确报告某疾病与某指标存在关联或组间差异，可建立 Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker。
8. 指标降低不代表关联被否定，不能仅据此使用 Negative。

### 2.6 GeneticFeature 和 MolecularFeature

常见 GeneticFeature 包括：

* DISC1 variant
* CACNA1C polymorphism
* BDNF polymorphism

分类规则：

1. 明确的基因变异、多态性或遗传改变归入 GeneticFeature。
2. 分子层面的状态或分子亚型可归入 MolecularFeature。
3. 不得把基因名称、基因变异和分子表型不加区分地统一归为一种类型。
4. 不得仅因为某遗传特征在精神类疾病研究中经常出现，就自动建立疾病关联关系。

### 2.7 ClinicalFeature

常见临床特征包括：

* cognitive impairment
* social dysfunction
* functional decline
* executive dysfunction
* psychopathology
* negative symptoms
* positive symptoms

分类规则：

1. 总体认知、功能状态或临床特征可归入 ClinicalFeature。
2. `negative symptoms` 和 `positive symptoms` 若指精神病理学中的症状维度，可依据领域语境归入 ClinicalFeature。
3. 若原文明确列出单项症状，应根据其实际语义考虑 Symptom。
4. 不得因为某临床特征在某疾病中常见，就自动建立关系。

### 2.8 Symptom

常见症状包括：

* hallucination
* delusion
* anxiety
* depressed mood
* anhedonia
* irritability
* inattention
* hyperactivity
* compulsion
* obsession

分类规则：

1. 必须根据原文实际语义区分 Symptom 与 ClinicalFeature。
2. `anxiety` 若指焦虑症状，可归入 Symptom；若指焦虑障碍诊断，则归入 Disease。
3. `depression` 若指抑郁障碍诊断，归入 Disease；若指情绪低落等症状，应按原文语义分类。
4. 不得仅凭症状推断疾病诊断。

### 2.9 Treatment

常见治疗实体包括：

* antipsychotics
* selective serotonin reuptake inhibitors
* mood stabilizers
* stimulants
* cognitive behavioral therapy

只有文献明确指出某治疗用于某疾病时，才建立 TREATED_BY。

药物若只作为研究干预或实验条件出现，不应自动视为常规临床治疗关系；需根据原文实际语义判断。

### 2.10 RiskFactor、Complication 和 Other

RiskFactor 常见例子：

* family history
* obstetric complications（仅在原文将其作为风险因素时）
* cannabis use
* childhood trauma
* urban upbringing

Complication 常见例子：

* suicide-related complication
* substance abuse
* metabolic syndrome

上述词语均须根据原文语境分类，不能仅凭词语本身决定其类型。

Other 常见例子：

* PANSS
* HAM-D
* YMRS
* ADHD-RS
* Y-BOCS
* BPRS
* MADRS

分类规则：

1. PANSS、HAM-D、YMRS、Y-BOCS、BPRS、MADRS 等作为量表或评分名称时归入 Other。
2. 只有原文明确说明量表评估的对象，才建立 ASSESSED_BY。
3. 不能因为某量表与某疾病同时出现，就自动认定该量表用于评估该疾病。
4. 不得把量表名称作为症状、疾病或生物标志物。

## 3. 精神类疾病领域常见关系模式

### 3.1 疾病与影像表现

Disease → HAS_FINDING → ImagingFinding

只有原文明确指出某疾病具有某种影像表现时才使用。

### 3.2 影像表现与序列

ImagingFinding → VISIBLE_ON → MRISequence

只有原文明确指出某影像表现可在某序列上观察到时才使用。

### 3.3 影像表现与解剖结构

ImagingFinding → LOCATED_IN → Anatomy

适用于原文明示某脑区激活、皮层变薄或其他影像表现位于某解剖区域的情况。

### 3.4 疾病与影像定量指标

Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker

适用于原文明确报告疾病与功能连接、ALFF、fALFF、ReHo、FA、灰质体积等指标存在关联或组间差异的情况。

如果原文主要表达组间差异，断言类型应使用 Comparative。

### 3.5 疾病与遗传特征

Disease → ASSOCIATED_WITH_GENETIC_FEATURE → GeneticFeature

适用于原文明确报告疾病与特定基因变异或遗传特征有关的情况。

### 3.6 疾病与分子特征

Disease → ASSOCIATED_WITH_MOLECULAR_FEATURE → MolecularFeature

适用于原文明确报告疾病与分子状态或分子亚型有关的情况。

### 3.7 疾病与临床表现

Disease → HAS_SYMPTOM → Symptom

适用于原文明示某疾病具有某种症状的情况。

如果原文只报告疾病与某种总体临床特征有关，应根据实际语义考虑 ASSOCIATED_WITH，而不是将其强行转化为 HAS_SYMPTOM。

### 3.8 疾病与治疗

Disease → TREATED_BY → Treatment

适用于原文明确说明某治疗用于某疾病的情况。

### 3.9 疾病或临床特征与量表

Disease 或 ClinicalFeature → ASSESSED_BY → Other

适用于原文明示量表用于评估某疾病或临床特征的情况。

## 4. 功能连接与脑区关系的特殊处理

精神影像研究中经常出现如下表达：

“Functional connectivity between region A and region B was decreased.”

这句话表达的是两个脑区之间的功能连接指标发生变化，而不是简单表示 region A 与 region B 存在一般关联。

处理规则：

1. 将原文明确出现的脑区 A、脑区 B 识别为 Anatomy 实体（若其独立 mention 及语义明确）。
2. 将 `functional connectivity` 识别为 Biomarker（前提是原文明确使用该指标概念）。
3. 不得建立 Anatomy A → ASSOCIATED_WITH → Anatomy B 来代替功能连接关系。
4. 不得建立 Anatomy A → LOCATED_IN → Anatomy B。
5. 不得把 `decreased` 作为独立实体。
6. 当前 Schema 没有专门表达“脑区 A 与脑区 B 之间某种连接指标发生变化”的关系类型时，不得强行生成一个失真的三元组。
7. 如果文献另外明确报告某疾病与 functional connectivity 指标存在关联，可独立抽取 Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker，但必须有该关系自己的直接证据。
8. 不得将功能连接降低自动解释为疾病加重或 Negative；应根据原文是否表达比较、关联或否定确定断言类型。

## 5. 精神类疾病领域的特别限制

1. 不得将 functional connectivity、ALFF、fALFF、ReHo 等指标归入 Anatomy。
2. 不得将指标降低或升高自动标记为 Negative。
3. 不得把脑区之间的功能连接简化为普通的脑区间 ASSOCIATED_WITH。
4. 不得因为某脑区与某疾病在同一段落中出现，就自动建立 LOCATED_IN 或 ASSOCIATED_WITH。
5. 不得将疾病诊断、症状、临床特征和量表名称混为一谈。
6. 不得仅根据量表名称推断其评估对象。
7. 不得仅根据影像结果推断精神疾病诊断。
8. 只有原文明确陈述时，才能建立 Disease → TREATED_BY → Treatment。
9. 所有关系必须符合 `AGENT_INSTRUCTION.md` 的 Domain/Range 和证据规范。

## 6. 示例

以下仅用于说明抽取方式，不可直接作为真实文献的抽取结果。

原文：

“Patients with schizophrenia showed decreased functional connectivity.”

实体：

* Disease：`schizophrenia`
* Biomarker：`functional connectivity`

关系：

* schizophrenia → ASSOCIATED_WITH_BIOMARKER → functional connectivity

断言类型：

* `Comparative` 仅在上下文明确表达组间比较或相对差异时使用。
* 若原文只明确表达关联，使用 `Association`。
* 不得仅因 `decreased` 就使用 `Negative`。

原文：

“Functional connectivity between the amygdala and prefrontal cortex was lower in patients with major depressive disorder than in controls.”

实体：

* Disease：`major depressive disorder`
* Anatomy：`amygdala`
* Anatomy：`prefrontal cortex`
* Biomarker：`functional connectivity`

可考虑抽取的关系：

* major depressive disorder → ASSOCIATED_WITH_BIOMARKER → functional connectivity

该关系仅在原文明确支持疾病与该指标之间的关系时成立。

不得抽取：

* amygdala → ASSOCIATED_WITH → prefrontal cortex

因为该关系无法保留原文“功能连接降低”的具体语义。

断言类型：

* `Comparative`

实际抽取时，应使用原文中能够直接支持每条关系的证据句，不能把示例文本作为真实证据。

## 7. 输出前检查

1. 是否正确区分 Disease、Symptom 和 ClinicalFeature。
2. 是否将功能连接、ALFF、fALFF、ReHo 等指标归入 Biomarker。
3. 是否正确区分影像表现和定量指标。
4. 是否将量表名称归入 Other，并明确其评估对象。
5. 是否避免将脑区间功能连接简化为普通脑区关联。
6. 是否避免将数值升高或降低自动解释为 Positive 或 Negative。
7. 是否避免仅凭影像结果推断疾病诊断。
8. 每条关系是否符合 `AGENT_INSTRUCTION.md` 的 Domain/Range 和证据规范。

输出结构、字段和路径必须遵循 `AGENT_INSTRUCTION.md`。
