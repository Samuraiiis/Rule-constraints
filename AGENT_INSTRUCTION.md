# AGENT_INSTRUCTION.md

# 脑部 MRI 医学文献实体与关系抽取总规范

## 1. 任务目标

本任务用于从脑部 MRI 相关医学文献的 MinerU OCR Markdown 文件中，抽取可追溯至原文的实体（Entity）及实体间关系（Relation），为后续知识图谱构建和 RAG 检索提供结构化数据。

抽取范围包括但不限于：

* 脑血管疾病；
* 脑肿瘤；
* 神经内科疾病；
* 精神类疾病；
* 上述疾病涉及的 MRI 影像表现、解剖结构、序列、诊断、治疗、病理、分子特征、遗传特征、临床表现和评估指标。

抽取时必须以当前文献原文为依据。不得根据医学常识补充文献未明确陈述的实体或关系。

## 2. 规则文件的使用顺序

抽取前应读取以下规则：

1. 本文件 `AGENT_INSTRUCTION.md`：定义全局实体类型、关系类型、断言类型、证据规范和输出格式。
2. 根据文献所属领域读取对应补充规则：

   * `disease_bt.md`：脑肿瘤；
   * `disease_cv.md`：脑血管疾病；
   * `disease_nl.md`：神经内科疾病；
   * `disease_ps.md`：精神类疾病。

领域规则用于补充领域术语、分类边界及典型抽取示例，不得擅自改变本文件中的全局 Schema。

若同一文献涉及多个疾病领域，可同时参考多个领域规则，但同一实体的分类仍须遵循本文件的统一标准。

如领域规则与本文件冲突，以本文件为准。若现有 Schema 无法准确表示原文事实，应舍弃该关系，不得通过更换为不匹配的关系类型来强行表达。

## 3. 输入与输出

### 3.1 输入

输入为 MinerU 转换后的 Markdown 文献文件。

抽取时应优先利用原文标题、正文、表格、图注、参考文献标记及页面标记等信息。对于 OCR 明显错误、内容残缺或无法确认的文本，不得自行补全医学事实。

### 3.2 输出路径

每篇文献生成一个 JSON 文件，保存至：

`data/agent_generated/{document_id}_unified.json`

其中 `{document_id}` 必须使用任务输入中已有的文献标识，不得自行创建或更改。

### 3.3 输出内容

输出仅包含：

* `document_id`
* `entities`
* `relations`

不要输出 `_summary`、解释性文字、Markdown 代码围栏或 Schema 中未定义的额外字段。

实体和关系的内部 ID 由后续 Python 后处理程序统一生成，因此本阶段不要自行生成实体 ID、关系 ID 或 Evidence ID。

## 4. 实体类型

每个实体必须使用以下 17 种类型之一。

### 4.1 Disease

疾病或临床诊断实体。

示例：ischemic stroke、glioblastoma、Alzheimer's disease、schizophrenia。

分类原则：

* 必须是文献明确讨论或诊断的疾病、疾病亚型或临床诊断。
* 不得仅因某种症状、影像表现或风险因素而推断患者患有某疾病。
* 当文献明确讨论的是疾病本身时，不要将其误标为 ClinicalFeature。

### 4.2 ImagingFinding

医学影像中观察到的征象、形态、信号表现或影像异常。

示例：restricted diffusion、contrast enhancement、white matter hyperintensity、cortical thinning、mass effect。

分类原则：

* 影像表现应有明确的影像语境。
* 同一术语若在文献中指病理过程、临床诊断或影像征象，应根据当前句子的实际含义分类。
* 不得将所有疾病相关的异常都自动分类为 ImagingFinding。

### 4.3 MRISequence

明确的 MRI 扫描序列或序列技术。

示例：T1WI、T2WI、FLAIR、DWI、SWI、GRE、ASL、PWI、DTI。

分类原则：

* 具体序列名称优先归入 MRISequence。
* DWI、FLAIR、SWI 等不得仅因用于诊断就归为 ImagingModality。
* MRA、fMRI 等术语需依据文献中的具体含义及领域规则判断；若表示专门的成像方式而非具体序列，归入 ImagingModality。
* 同一文献中的同一含义应保持分类一致。

### 4.4 Anatomy

人体解剖结构、脑区、脑叶、血管及明确的解剖区域。

示例：hippocampus、amygdala、thalamus、corpus callosum、middle cerebral artery。

分类原则：

* 必须是明确的解剖结构或区域。
* 不要把疾病、影像征象、功能连接指标或脑网络指标归为 Anatomy。

### 4.5 Treatment

明确的治疗方式、治疗操作或治疗药物。

示例：thrombolysis、mechanical thrombectomy、radiotherapy、temozolomide、levodopa、cognitive behavioral therapy。

分类原则：

* 治疗相关实体必须在原文中承担治疗或干预含义。
* 药物若仅用于实验或成像示踪，不得自动归为 Treatment。
* 治疗措施和评估方法不得混淆。

### 4.6 Biomarker

用于反映疾病状态、组织状态、影像定量特征或生物学状态的标志物及定量指标。

示例：ADC、rCBV、FA、NAA/Cr、ALFF、ReHo、functional connectivity、Ki-67。

分类原则：

* 定量指标、影像衍生指标及明确的生物标志物归入 Biomarker。
* 不要把“升高”“降低”“异常”等变化描述作为独立 Biomarker；实体应为被测量的指标本身。
* 临床量表或疾病严重程度评分默认归入 Other，除非后续 Schema 增加专门的量表类型。
* 若某术语既可表示指标又可表示生物分子，应按文献当前语境分类。

### 4.7 Pathology

明确的病理组织学表现、病理过程或组织病理学特征。

示例：microvascular proliferation、neuronal loss、demyelination、Lewy bodies、neurofibrillary tangles。

分类原则：

* 只有在原文指向病理组织学或病理过程时才使用 Pathology。
* necrosis、hemorrhage、infarction 等词应依据语境判断；影像表现应优先归入 ImagingFinding，疾病诊断或病理过程则按其实际含义分类。
* 不要将 WHO grade 等疾病分级属性自动视为 Pathology 实体。

### 4.8 MolecularFeature

明确的分子特征、分子亚型或分子层面的异常。

示例：IDH-related molecular subtype、MGMT promoter methylation（当文献强调其分子特征含义时）、glutamate-related molecular alteration。

分类原则：

* 当文献强调某种分子状态或分子亚型时，可使用 MolecularFeature。
* 若实体明确指某基因发生的突变、扩增、缺失或其他遗传改变，优先考虑 GeneticFeature。
* 同一术语不得仅因句式不同而随意在 MolecularFeature 与 GeneticFeature 之间切换。

### 4.9 GeneticFeature

明确的基因、遗传变异、基因突变、扩增、缺失、染色体改变或其他遗传特征。

示例：EGFR amplification、TP53 mutation、BRAF V600E mutation、1p/19q codeletion、APOE ε4 allele。

分类原则：

* 必须有明确的遗传学含义。
* 不得把未指明遗传变化的泛化“分子异常”自动分类为 GeneticFeature。
* 基因名称本身是否作为独立实体抽取，应由其在当前句中的实际语义决定。

### 4.10 ClinicalFeature

疾病的临床特征、功能状态、认知状态或临床结局特征，但不属于明确的单项症状、风险因素或并发症。

示例：cognitive decline、functional outcome、executive dysfunction、radiographic response（若作为临床研究结局特征使用）。

分类原则：

* 当术语表达的是总体临床状态或功能特征时使用 ClinicalFeature。
* 明确的单项症状优先使用 Symptom。
* 明确的危险因素优先使用 RiskFactor。
* 明确的并发症优先使用 Complication。
* 临床量表名称默认归入 Other。

### 4.11 Symptom

明确的症状或患者主观、客观表现。

示例：headache、seizure、tremor、hallucination、anhedonia、dizziness。

分类原则：

* 需在原文中承担症状含义。
* 不要将影像征象、实验室指标或总体疾病诊断归入 Symptom。
* “negative symptoms”等术语需根据原文含义判断；若其是精神病理学的症状维度，可按领域规则分类。

### 4.12 RiskFactor

文献明确指出与疾病发生或风险增加有关的因素。

示例：hypertension、smoking、atrial fibrillation、childhood trauma、family history。

分类原则：

* 必须有原文证据表明其作为疾病风险因素或易感因素。
* 不得因为某个实体与疾病同时出现就自动建立风险关系。

### 4.13 Complication

疾病、治疗或临床过程所涉及的明确并发症。

示例：hemorrhagic transformation、brain herniation、infection、metabolic syndrome。

分类原则：

* 必须在原文中具有并发症含义。
* 一般症状、伴随征象或单纯统计关联不能自动认定为并发症。

### 4.14 StudyPopulation

研究中明确界定的人群、患者亚组或对照组。

示例：patients with acute ischemic stroke、healthy controls、patients with first-episode schizophrenia。

分类原则：

* 只在研究人群具有明确分析意义时抽取。
* 不要将每个泛化的“patients”都作为独立实体。
* 不得把 StudyPopulation 与 Disease 混为一谈。

### 4.15 ImagingModality

明确的医学成像方式或成像模态。

示例：MRI、fMRI、MRA、PET、CT。

分类原则：

* MRI 作为整体检查方式时归入 ImagingModality。
* 具体 MRI 序列优先归入 MRISequence。
* fMRI、MRA 等若在文献中明确表示成像方式，归入 ImagingModality。
* 不能仅因为一个术语包含 MRI 或 MRA 就忽略其实际语义。

### 4.16 ContrastAgent

明确用于医学成像的造影剂或示踪剂。

示例：gadolinium-based contrast agent。

分类原则：

* 必须明确承担造影或成像示踪作用。
* 不要将普通治疗药物或一般化学物质自动归入 ContrastAgent。

### 4.17 Other

无法归入以上任何类型、但在原文中具有明确意义且对研究内容有价值的实体。

示例：NIHSS、mRS、KPS、MMSE、MoCA、PANSS 等临床量表或评分名称。

分类原则：

* Other 是受限兜底类型，不是默认类型。
* 不得为了绕过 Schema 限制而将疾病、解剖结构、影像征象或生物标志物归入 Other。
* 统计指标、评价工具或模型性能指标仅在符合关系规则时才抽取。
* 若某实体只能通过 Other 才能保留，但没有合法关系可以表达其作用，可以只抽取实体，不强行构造关系。

## 5. 实体抽取规则

### 5.1 原文一致性

`mention` 必须是原文中的连续字面表达，不得自行翻译、改写、纠错、缩写或扩写。

例如，原文出现 `hippocampal atrophy`，不得将 `mention` 改成 `atrophy`，除非原文中确实单独出现了 `atrophy` 且抽取的是该处独立概念。

实体规范化和同义词合并由后续程序处理，本阶段不得修改原始 mention。

### 5.2 source_text

`source_text` 必须是包含该实体的原文片段，尽量使用能够独立说明其含义的完整句子。

不得将不同句子拼接成原文中不存在的句子。

若一个实体在文献中多次出现，可选取最能明确其语义的一个原文片段。

### 5.3 page

`page` 只能依据 MinerU Markdown 中明确的页面标记填写。

* 有可确认的页面标记：填写对应页面标记所表示的页码。
* 没有页面标记或无法可靠确定：填写 `null`。
* 不得根据 PDF 印刷页码、文献页脚、章节页码或模型推测自行填写。

### 5.4 section

`section` 仅在文献中存在明确且可确认的章节标题时填写。

* 能确认所属章节：填写原文章节标题。
* 无法确认：填写 `null`。
* 不得凭语义推测章节名称。

### 5.5 实体重复与粒度

* 同一 mention 在不同语境中含义不同，可以按不同实体类型分别抽取，但必须有明确证据支持。
* 不要把同一实体的长短表述无条件当作两个独立概念。
* 不要把复合实体拆成多个实体，除非原文确实分别讨论了这些概念。
* 不要把数值变化、比较词或修饰词当作独立实体。
* 不能仅凭医学常识推断原文未提及的实体。

## 6. 关系类型及 Domain/Range

仅允许使用以下关系类型。关系方向必须符合本节定义。

### 6.1 HAS_FINDING

Domain：Disease
Range：ImagingFinding

表示文献明确指出某疾病具有某种影像表现。

### 6.2 VISIBLE_ON

Domain：ImagingFinding
Range：MRISequence

表示文献明确指出某影像表现可在某 MRI 序列上观察到。

不能仅因为某序列用于诊断该疾病，就自动建立 VISIBLE_ON。

### 6.3 LOCATED_IN

Domain：ImagingFinding、Disease、Pathology
Range：Anatomy

表示文献明确指出某影像表现、疾病病灶或病理改变位于某解剖结构。

不得将 Biomarker、MRISequence、Treatment 或其他类型作为该关系的头实体，除非未来统一修改 Schema 并同步更新所有校验程序。

### 6.4 DIAGNOSED_BY

Domain：Disease
Range：ImagingModality、MRISequence

表示文献明确指出某疾病通过某成像方式或 MRI 序列进行诊断或识别。

“用于评估”“与疾病有关”不必然等于“用于诊断”。

### 6.5 DIFFERENTIAL_DIAGNOSIS

Domain：Disease
Range：Disease

表示文献明确指出两种疾病需要鉴别，或一疾病用于另一疾病的鉴别诊断。

不得根据疾病相似性自行推断。

### 6.6 HAS_SYMPTOM

Domain：Disease
Range：Symptom

表示文献明确指出某疾病具有某种症状。

若原文仅表述两个临床特征相关，不能自动改写为 HAS_SYMPTOM。

### 6.7 HAS_RISK_FACTOR

Domain：Disease
Range：RiskFactor

表示文献明确指出某因素是疾病的危险因素或易感因素。

### 6.8 HAS_COMPLICATION

Domain：Disease
Range：Complication

表示文献明确指出某并发症与某疾病有关，且具有并发症语义。

### 6.9 TREATED_BY

Domain：Disease
Range：Treatment

表示文献明确指出某疾病采用某治疗方法或药物治疗。

不得将仅在实验方法中使用的药物自动作为疾病治疗关系。

### 6.10 RECOMMENDED_BY

当前禁用。

若未在 Schema、后处理程序及相关规则中正式启用，不得输出该关系。

### 6.11 PREDICTS

Domain：任意已定义实体类型
Range：任意已定义实体类型

表示文献明确指出某实体可预测另一实体、结局或事件。

预测关系必须有明确的预测语义，不得将一般相关性自动解释为预测关系。

### 6.12 ASSOCIATED_WITH

Domain：任意已定义实体类型
Range：任意已定义实体类型

表示文献明确陈述两个实体存在关联，但没有更适合的专用关系类型。

使用前应优先检查是否有更具体的关系类型，例如 ASSOCIATED_WITH_BIOMARKER、ASSOCIATED_WITH_MOLECULAR_FEATURE 或 ASSOCIATED_WITH_GENETIC_FEATURE。

不得仅因两个实体出现在同一句话中就建立关联。

### 6.13 ASSOCIATED_WITH_BIOMARKER

Domain：Disease
Range：Biomarker

表示文献明确指出某疾病与某生物标志物或影像定量指标相关。

例如，文献明确报告某疾病患者的 ADC 值存在差异，可以根据实际句义建立该关系。具体数值变化应通过证据原文保留，不得将“降低”直接解释为 Negative。

### 6.14 ASSOCIATED_WITH_MOLECULAR_FEATURE

Domain：Disease
Range：MolecularFeature

表示文献明确指出某疾病与某分子特征或分子亚型相关。

### 6.15 ASSOCIATED_WITH_GENETIC_FEATURE

Domain：Disease
Range：GeneticFeature

表示文献明确指出某疾病与某遗传特征相关。

### 6.16 HAS_PATHOLOGY

Domain：Disease
Range：Pathology

表示文献明确指出某疾病具有某种病理学特征或病理改变。

不得把疾病分级、分期或一般影像表现直接作为 Pathology。

### 6.17 ASSESSED_BY

Domain：任意已定义实体类型
Range：明确的评估工具、量表或评价指标实体

表示文献明确指出某对象通过某量表、评分或评价工具进行评估。

当前 Schema 未设置专门的量表实体类型，因此 NIHSS、mRS、KPS、MMSE、MoCA、PANSS 等可归入 Other。

使用 ASSESSED_BY 时，必须明确评估对象。例如：

* Disease → ASSESSED_BY → Other（量表）
* ClinicalFeature → ASSESSED_BY → Other（量表）

不得仅因某量表在同一段中出现，就推断其评估对象。

Range 中的实体必须实际承担评估工具或评价指标含义，不得将普通治疗设备、刺激设备或侵入性操作作为量表使用。

### 6.18 COMPARED_WITH

Domain：任意已定义实体类型
Range：任意已定义实体类型

表示文献明确对两个对象进行比较。

比较对象可以是疾病、方法、指标、模型或研究组，但必须在原文中具有明确比较关系。

### 6.19 IMPROVES

Domain：任意已定义实体类型
Range：任意已定义实体类型

表示文献明确指出头实体改善、提高或优化尾实体所代表的结果、性能或状态。

若头实体为技术方法，尾实体通常应是性能指标、任务表现或其他技术方法。

若头实体为 Treatment，尾实体可以是疾病相关状态、症状或临床结局，但必须有明确治疗效果证据。

### 6.20 WORSENS

Domain：任意已定义实体类型
Range：任意已定义实体类型

表示文献明确指出头实体使尾实体所代表的结果、性能或状态恶化。

不得将单纯的数值降低自动视为 WORSENS；需要结合指标方向和原文实际含义判断。

### 6.21 CORRELATES_WITH

Domain：任意已定义实体类型
Range：任意已定义实体类型

表示文献明确报告统计学或定量意义上的相关关系。

如果原文只表述两个实体共现、差异或组间比较，不能自动建立 CORRELATES_WITH。

### 6.22 OTHER

当前禁用。

不得把不符合已有关系类型的关系统一输出为 OTHER。若现有关系集合不能准确表达原文关系，应舍弃该关系，并保留能够独立成立的实体。

## 7. 断言类型

每条关系必须使用以下 9 种断言类型之一：

* `Positive`
* `Negative`
* `Uncertain`
* `Conditional`
* `Comparative`
* `Recommendation`
* `Association`
* `Prediction`
* `Unknown`

为避免类型重叠，按以下顺序确定唯一的 `assertion_type`：

1. `Conditional`：关系仅在明确条件成立时成立。
2. `Uncertain`：原文明确表示可能、不确定、尚未证实或证据不足。
3. `Recommendation`：原文表达建议、推荐或指南性意见。
4. `Negative`：原文明确否定该关系、明确表示不存在或未发现相关联系。
5. `Prediction`：原文明确表达预测、预后预测或未来结果预测。
6. `Comparative`：原文主要表达组间比较、数值差异或相对高低。
7. `Association`：原文明确表达关联、相关或联系。
8. `Positive`：原文明确肯定某项事实或关系，且不符合以上更具体类型。
9. `Unknown`：原文无法支持明确判断，但仍有理由保留该关系；应谨慎使用。

补充说明：

* 数值降低、升高、增加或减少，不等于 Negative。
* “未发现显著差异”或“无显著相关性”才可能使用 Negative，前提是原文确实明确否定相关关系。
* “可能相关”优先使用 Uncertain，而不是 Association。
* “与对照组相比更高”优先使用 Comparative。
* `PREDICTS` 关系通常使用 Prediction。
* `ASSOCIATED_WITH` 等关系名称不意味着断言类型必须为 Association；若原文明确否定该关系，仍应使用 Negative。
* 不得仅凭句子中存在 may、might、could 等词就机械判断，应结合完整语境。

## 8. 关系抽取的证据要求

### 8.1 必须有直接证据

每条关系的 `source_text` 必须包含能够直接支持该关系的原文片段，并且应同时包含头实体和尾实体的 mention。

如果两个实体出现在不同句子中，只有在原文明确建立两者关系时才允许抽取；不得把相邻句子中的实体自行组合成关系。

### 8.2 不得依赖医学常识推断

以下情况不得直接建立关系：

* 两个实体只是在同一句话或同一段落中共同出现。
* 某疾病通常具有某种征象，但当前文献未明确陈述。
* 某 MRI 序列通常用于评估某疾病，但当前文献没有相应诊断或观察证据。
* 某生物标志物在医学上常与某疾病有关，但当前文献未建立该关系。
* 两个脑区的功能连接降低，但原文没有把两个脑区作为独立关联对象建立关系。
* 某治疗通常用于某疾病，但当前文献未说明治疗对象。

### 8.3 研究结果与方法描述

方法部分中关于扫描参数、数据预处理、统计分析、模型训练、特征提取和评估流程的描述，不得自动转化为疾病事实关系。

如果方法部分明确说明某工具或量表用于评估某对象，可以在满足 ASSESSED_BY 规则时抽取该关系。

如果结果部分明确报告观察到的影像表现、定量差异、相关性或预测结果，可以依据其实际语义建立关系。

不能仅凭“observed”“identified”“used”等单个动词机械决定是否抽取，应结合整句含义判断。

### 8.4 文献引用与背景陈述

若句子明确在转述既往研究，且没有证据表明该结论属于当前研究，应避免将其误标为当前研究的实验结果。

但若任务目标是抽取整篇文献中所有明确陈述的医学知识，可以保留文献明确引用的事实关系；不得把既往研究的结果改写成当前研究新发现。

### 8.5 否定与不确定性

必须保留原文的否定、限定和不确定语义。

例如：

* “No significant association was found” 不得抽取为肯定关联。
* “The finding may indicate disease progression” 不得抽取为确定的诊断结论。
* “The marker was lower in group A than group B” 不得直接抽取为 Negative 关联。

### 8.6 关系方向

关系方向必须遵守本文件定义。

例如：

* Disease → ASSOCIATED_WITH_BIOMARKER → Biomarker
* Disease → ASSOCIATED_WITH_MOLECULAR_FEATURE → MolecularFeature
* Disease → ASSOCIATED_WITH_GENETIC_FEATURE → GeneticFeature
* Disease → HAS_FINDING → ImagingFinding
* ImagingFinding → VISIBLE_ON → MRISequence
* ImagingFinding → LOCATED_IN → Anatomy
* Disease → TREATED_BY → Treatment

不得因为原文句子的主语顺序不同而随意改变方向。

### 8.7 方法与性能指标

统计指标、量表分数或模型性能数值不能作为任意关系的通用尾实体。

只有在 COMPARED_WITH、ASSESSED_BY、IMPROVES 等关系确实符合原文语义时，才允许建立相应关系。

## 9. JSON 字段规范

### 9.1 Entity

每个实体必须包含以下字段：

* `entity_type`：17 种实体类型之一。
* `mention`：原文中的连续字面表达。
* `source_text`：包含该实体的原文片段。
* `page`：页面标记对应的页码；无法确定时为 null。
* `section`：明确的原文章节标题；无法确定时为 null。

### 9.2 Relation

每条关系必须包含以下字段：

* `head_mention`：头实体的原文 mention。
* `head_type`：头实体类型。
* `relation_type`：22 种关系类型之一，但不得使用已禁用的 RECOMMENDED_BY 和 OTHER。
* `tail_mention`：尾实体的原文 mention。
* `tail_type`：尾实体类型。
* `assertion_type`：9 种断言类型之一。
* `source_text`：支持该关系的原文证据，必须包含头实体和尾实体的 mention。
* `page`：关系证据所在页面；无法确定时为 null。
* `section`：关系证据所在章节；无法确定时为 null。

不得自行添加未定义字段。

## 10. 输出前校验

输出 JSON 前必须检查：

1. JSON 语法正确，可被标准 JSON 解析器读取。
2. `document_id` 与输入文献标识一致。
3. 所有实体类型均属于已定义的 17 种类型。
4. 所有关系类型均属于已定义关系集合，且没有使用禁用关系。
5. 所有断言类型均属于已定义的 9 种类型。
6. 每条关系的头实体和尾实体均能在 `entities` 中找到。
7. 关系的头尾 mention 和类型必须与对应实体完全一致。
8. 每条关系符合对应关系的 Domain/Range 约束。
9. 每条关系的 source_text 能够直接支持该关系，并包含头尾实体的 mention。
10. `page` 和 `section` 不得凭空推断。
11. 不得输出自环关系，即头尾为同一实体且表达同一概念的关系。
12. 不得因同一事实存在长短表述而生成明显重复的关系。
13. 不得为了满足关系数量或实体覆盖率而编造关系。
14. 若证据不足，宁可不输出关系，也不能依靠医学常识补全。
15. 输出文件路径必须为 `data/agent_generated/{document_id}_unified.json`。

实体数量、关系数量、关系实体比等统计指标仅用于后续质量检查，不得作为要求模型强行增加实体或关系的生成目标。

## 11. 输出格式示例

以下仅用于说明 JSON 结构。实际抽取时必须使用输入文献中的真实原文，不得复制示例事实。

{
"document_id": "example_document",
"entities": [
{
"entity_type": "Disease",
"mention": "acute ischemic stroke",
"source_text": "Acute ischemic stroke was diagnosed by DWI in all cases.",
"page": null,
"section": null
},
{
"entity_type": "MRISequence",
"mention": "DWI",
"source_text": "Acute ischemic stroke was diagnosed by DWI in all cases.",
"page": null,
"section": null
}
],
"relations": [
{
"head_mention": "acute ischemic stroke",
"head_type": "Disease",
"relation_type": "DIAGNOSED_BY",
"tail_mention": "DWI",
"tail_type": "MRISequence",
"assertion_type": "Positive",
"source_text": "Acute ischemic stroke was diagnosed by DWI in all cases.",
"page": null,
"section": null
}
]
}

注意：示例仅用于展示字段及关系方向，不代表任何待处理文献的实际内容。抽取时不得将示例实体、关系或证据带入真实输出。
