# 脑部 MRI 文献知识抽取 Schema 约束规范

**版本：** V1.0（已通过代码测试确认 2026-10-10）\
**适用范围：** Evidence、Entity、Relation
后处理对象的结构校验与关联规则。

## 1. 目的与原则

本规范统一脑部 MRI 文献知识抽取中 Evidence、Entity、Relation
的字段结构与校验职责。所有字段和枚举应以当前运行代码为依据，不得为了"看起来完整"而新增代码不会生成或消费的字段。

1.  JSON Schema 校验后处理后的单条 Evidence、Entity、Relation
    对象，不直接校验 LLM 原始输出。
2.  JSON Schema 负责必填字段、字段类型、枚举及额外字段约束。
3.  `rule_validator.py`
    负责跨对象引用、文献一致性、Domain/Range、自环等业务规则。
4.  `evidence_type`
    当前没有统一受控词表，因此仅限制为非空字符串，不擅自增加枚举。
5.  原文真实性和关系语义是否受到原文支持，不能仅靠 JSON Schema 判断。

## 2. 校验对象与处理阶段

统一抽取流程的目标校验对象为后处理结果 `result.processed`：

`LLM 原始响应 → 原始字段解析与检查 → Python 后处理 → processed{evidences, entities, relations} → JSON Schema 校验 → 业务规则校验`

对应文件：

-   `schemas/evidence.schema.json`：校验 `processed["evidences"]`
    中的单条 Evidence。
-   `schemas/entity.schema.json`：校验 `processed["entities"]` 中的单条
    Entity。
-   `schemas/relation.schema.json`：校验 `processed["relations"]`
    中的单条 Relation。
-   `pipeline/json_schema_validator.py`：加载 Schema 并执行结构校验。
-   `pipeline/rule_validator.py`：执行跨对象和业务规则校验。
-   `pipeline/unified_extractor.py`：统一抽取、后处理与校验编排。
-   `agent_generated/scripts/check_agent_raw.py`：原始抽取结果质检，不等同于后处理对象的
    JSON Schema 校验。

## 3. 后处理对象字段

### 3.1 Evidence

  字段                   类型                       含义
  ---------------------- -------------------------- ------------------------------------
  `evidence_id`          string                     程序生成的证据标识
  `document_id`          string                     所属文献标识
  `evidence_type`        string                     当前由后处理逻辑赋值；暂不使用枚举
  `evidence_statement`   string                     当前由原文片段截取生成的证据摘要
  `source_text`          string                     原文证据
  `section`              string 或 null             章节标题，未知时为 null
  `page`                 positive integer 或 null   页面标记对应页码，未知时为 null
  `assertion_type`       enum                       当前使用断言类型枚举
  `entities`             array\[string\]            与该证据关联的 Entity ID

### 3.2 Entity

  字段               类型                       含义
  ------------------ -------------------------- ----------------------------------
  `entity_id`        string                     程序生成的实体标识
  `document_id`      string                     所属文献标识
  `entity_type`      enum                       17 种实体类型之一
  `mention`          string                     原文中的实体表达
  `source_text`      string                     实体所在原文片段
  `page`             positive integer 或 null   页面标记对应页码
  `section`          string 或 null             章节标题
  `evidence_ids`     array\[string\]            支持该实体的 Evidence ID
  `canonical_name`   string 或 null             标准化名称；未命中时允许 null
  `ontology_id`      string 或 null             本体/词典标识；未命中时允许 null

### 3.3 Relation

  字段               类型              含义
  ------------------ ----------------- --------------------------
  `relation_id`      string            程序生成的关系标识
  `document_id`      string            所属文献标识
  `head_entity_id`   string            头实体 ID
  `tail_entity_id`   string            尾实体 ID
  `relation_type`    enum              已定义关系类型之一
  `assertion_type`   enum              断言类型之一
  `evidence_ids`     array\[string\]   支持该关系的 Evidence ID

最终 Relation 不直接保存 `source_text`、`page` 或
`section`；这些信息通过 `evidence_ids` 追溯。

## 4. 枚举

### 4.1 Entity 类型

`Disease`、`ImagingFinding`、`MRISequence`、`Anatomy`、`Treatment`、`Biomarker`、`Pathology`、`MolecularFeature`、`GeneticFeature`、`ClinicalFeature`、`Symptom`、`RiskFactor`、`Complication`、`StudyPopulation`、`ImagingModality`、`ContrastAgent`、`Other`。

### 4.2 Relation 类型

`HAS_FINDING`、`VISIBLE_ON`、`LOCATED_IN`、`DIAGNOSED_BY`、`DIFFERENTIAL_DIAGNOSIS`、`HAS_SYMPTOM`、`HAS_RISK_FACTOR`、`HAS_COMPLICATION`、`TREATED_BY`、`RECOMMENDED_BY`、`PREDICTS`、`ASSOCIATED_WITH`、`ASSOCIATED_WITH_BIOMARKER`、`ASSOCIATED_WITH_MOLECULAR_FEATURE`、`ASSOCIATED_WITH_GENETIC_FEATURE`、`HAS_PATHOLOGY`、`ASSESSED_BY`、`COMPARED_WITH`、`IMPROVES`、`WORSENS`、`CORRELATES_WITH`、`OTHER`。

枚举用于限制可识别的关系类型，并不表示所有枚举值当前都允许模型生成。`RECOMMENDED_BY`
与 `OTHER` 的启用限制应由现有 Prompt
和业务校验器执行；不得因其存在于枚举中而绕过业务限制。

### 4.3 Assertion 类型

`Positive`、`Negative`、`Uncertain`、`Conditional`、`Comparative`、`Recommendation`、`Association`、`Prediction`、`Unknown`。

注意：Evidence 当前由后处理程序默认赋值
`Positive`。除非代码实现了明确的同步逻辑，否则不要假定 Evidence 的
`assertion_type` 会自动继承某条 Relation 的断言类型。

## 5. Schema 与业务规则的职责边界

  -----------------------------------------------------------------------
  规则                                应由谁执行
  ----------------------------------- -----------------------------------
  必填字段、类型、枚举、额外字段      JSON Schema

  头尾实体 ID 是否存在                `rule_validator.py`

  Evidence ID 是否存在                `rule_validator.py`

  Entity、Relation、Evidence 的       `rule_validator.py`
  `document_id` 一致性                

  Domain/Range                        `rule_validator.py`

  头尾实体是否构成自环                `rule_validator.py`

  ID 的生成与去重                     ID 生成及后处理程序

  `source_text` 是否逐字存在于原文    原始数据质检程序

  原文是否真正支持关系语义            原始质检与人工/模型语义审核
  -----------------------------------------------------------------------

JSON Schema 中的 `additionalProperties: false`
用于保证后处理对象字段稳定；如需增加字段，应先确认后处理代码实际生成该字段，再同步更新
Schema、代码、规范与测试。

## 6. 原始 Relation 字段命名

当前已统一使用 `head_entity_type` 和
`tail_entity_type`，与统一抽取代码和 Prompt
一致。`docs/v2/AGENT_INSTRUCTION.md` 中原有的 `head_type` /
`tail_type` 已修正为上述标准名称（L636、L639、L694、L697）。

原始 Relation 与后处理 Relation 是不同数据结构：原始阶段使用
`head_mention`、`head_entity_type`、`tail_mention`、`tail_entity_type`
等字段；后处理阶段使用
`head_entity_id`、`tail_entity_id`。不得把原始字段直接加到最终 Relation
Schema 中。

## 7. 部署前检查清单

1.  确认 `schemas/` 目录及三个 Schema 文件已提交到运行分支。
2.  确认 `json_schema_validator.py` 实际加载的路径与文件名一致。
3.  ~~将 `AGENT_INSTRUCTION.md` 中的关系字段名统一为 `head_entity_type` /
    `tail_entity_type`。~~ **已完成（2026-10-10）**
4.  用真实的后处理输出分别测试三种对象的合法样例。
5.  测试缺失字段、错误类型、非法枚举、额外字段、null
    页码/章节等结构错误。
6.  测试无效实体/证据引用、跨文献引用、Domain/Range
    不匹配、自环和禁用关系等业务错误。
7.  只有通过代码与样例验证后，才将本规范标记为正式发布版本。

## 8. 版本状态

本规范与随附 Schema 文件为**待代码测试确认版本**。Schema
只约束单对象结构；跨对象引用和医学语义真实性仍需由业务规则、原文质检及适当的人工审核保障。
