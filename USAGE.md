# 使用说明 — 最终版脚本与文件清单（v2）

> 更新时间：2026-10-09（v2 分疾病系重构后）
> 定位：**目录导航 + 数据流 + 每个保留脚本的使用说明**。
> Agent 抽取指令见 [AGENT_INSTRUCTION.md](AGENT_INSTRUCTION.md)（共享基础），
> 疾病系专属规则见 [disease_bt.md](disease_bt.md) / [disease_cv.md](disease_cv.md) / [disease_nl.md](disease_nl.md) / [disease_ps.md](disease_ps.md)。
> 历史产物（旧三阶段抽取器、一次性脚本、旧版缓存与 QA 报告）全部归档在 `_archive/`，不参与运行。
> OCR 识别侧（`batch_mineru_api.py`、`mineru.zip`、`results/`）属于上游数据生产，本说明不展开。

---

## 1. 目录结构（注释版）

```
mineru/
├── README.md                     # 项目总览 + 快速开始
├── docs/                         # 全部文档
│   ├── v1/                    # v1 归档（历史版本）
│   │   ├── AGENT_INSTRUCTION.md
│   │   ├── EXTRACTION_SPEC.md
│   │   ├── RULES.md
│   │   └── USAGE.md
│   └── v2/                    # v2 当前版本
│       ├── AGENT_INSTRUCTION.md   # 共享基础规则
│       ├── disease_bt.md          # 脑肿瘤专属
│       ├── disease_cv.md          # 脑血管疾病专属
│       ├── disease_nl.md          # 神经内科疾病专属
│       ├── disease_ps.md          # 精神类疾病专属
│       └── USAGE.md
├── pipeline/                     # 核心库（14 模块 + prompts/4）
├── agent_generated/              # Agent 直读标注路线
│   ├── agent_input_v2/           # 12 篇分层样本输入（带 1..N 页码 marker 的重建 Markdown）
│   ├── gold/                     # 抽样清单 stratified_sample_v3.{json,md} + 8 篇历史 raw
│   └── scripts/                  # 标注路线脚本 4 个（§4）
├── scripts/                      # 通用工具脚本 3 个（§5）
├── data/
│   ├── agent_generated/          # 标注产出（契约路径，勿改名）：{doc_id}_unified.json ×12 + 4 个 .v3bak
│   │   └── audits/               # 审计报告：SUMMARY.{md,json}、rule_v3_effect_audit.md、stratified_metrics_v3 等
│   └── extracted/                # 抽取缓存，按 RUN_VERSION 分目录
│       ├── DeepSeek-V4-Flash/    # API 路线缓存
│       └── Agent-Gold-Strat12{,-v2,-v3}/  # 标注路线缓存（v3 = 当前规则口径）
├── metadata/                     # 文献元数据三层 CSV（§6）
│   ├── first/                    # 原始层：file_index.csv、document_metadata.csv、crossref_cache.json 等
│   ├── filter/                   # 过滤层：keep_true / keep_review / keep_false.csv
│   └── final/                    # 最终层：keep_true / keep_review / keep_false.csv（含 note 列）
├── Schema_rule/                  # 四份契约（只读，不可修改）
├── schemas/                      # JSON Schema：evidence / entity / relation
├── dictionaries/                 # 6 类词典 CSV（build_dictionaries.py 产出）
├── results/                      # MinerU OCR 产出（12,458+ 篇 .md / content_list_v2.json 等）【OCR 侧】
├── pdfs/ unrelated/ get_metadata/  # 上游数据与检索侧【OCR 侧，本文不展开】
├── batch_mineru_api.py           # MinerU 批量 OCR 提交脚本【OCR 侧】
├── .env                          # LLM 配置（§7）
└── _archive/                     # 历史产物归档（旧三阶段 pipeline、一次性脚本、旧缓存/QA/备份，仅回退用）
```

---

## 2. 数据流转（Agent 直读路线，当前主线）

```
results/*.md（OCR 产出）
    │  pipeline.markdown_reader.MarkdownReaderImpl.read()
    ▼  注入 <!-- page: N printed: M --> 页码 marker，重建 Markdown
agent_generated/agent_input_v2/{doc_id}.md        ← 标注输入（分层抽样 12 篇）
    │  标注 Agent 直读，按 document_id 前缀选 disease_*.md + docs/v2/AGENT_INSTRUCTION.md 抽取
    │  （API 路线：unified_extractor._extract_single 调 select_profile(doc_id) → build_system_prompt(profile) 注入疾病系差异段）
    ▼
data/agent_generated/{doc_id}_unified.json        ← raw 产出（entities + relations，无 ID；抽完跑 ensure_summary.py 补 _summary）
    │  agent_generated/scripts/check_agent_raw.py  ← 落盘前质检门（error 拦截 / WARN 复查队列）
    ▼
pipeline.unified_extractor {doc} --from-file ...   ← 后处理：Evidence 包装、ID 分配、
    │                                               词典标准化、P7 校验；不调 LLM
    ▼
data/extracted/{RUN_VERSION}/{doc_id}_unified.json ← 统一缓存（RUN_VERSION=Agent-Gold-Strat12-v3 等）
    │  scripts/summarize_agent_outputs.py          ← 汇总指标 + 复查队列 → data/agent_generated/audits/
    │  agent_generated/scripts/build_audit_sheet.py ← 人工审阅清单（抽样逐条对照原句）
    ▼
人工审阅（精确率抽查）→ 规则迭代 → 下一轮 RUN_VERSION
```

> **v2 profile 路由**：读取 Markdown → 读取元数据 → 调用 LLM 抽取的链路中，
> `unified_extractor._extract_single` 会按 `document_id` 前缀调用
> `pipeline.prompts.disease_profiles.select_profile(doc_id)` 选择疾病系 profile
> （BT→脑肿瘤 / CV→脑血管 / NL→神经内科 / PS→精神类 / 其他→通用），
> 再传入 `build_system_prompt(profile)` 将疾病系专属差异段注入 system prompt。
> Agent 直读路线由标注 Agent 自行按前缀选 `disease_*.md`。

**职责铁律**（EXTRACTION_SPEC §1）：发现实体/判断关系/挑 source_text 归抽取方；
生成任何 `*_id`、去重合并、词典标准化归 Python。抽取方禁止输出 ID 字段。

**ID 规则**（pipeline/id_generator.py，sha256 确定性派生，前缀 EV/ENT/R）：

```
evidence_id  = {doc_id}-EV-{sha256(doc_id+source_text)[:8]}
entity_id    = {doc_id}-ENT-{sha256(doc_id+mention+entity_type)[:8]}      # 同 mention+type 自动合并
relation_id  = {doc_id}-R-{sha256(doc_id+head_entity_id+relation_type+tail_entity_id)[:8]}
```

---

## 3. pipeline/ 核心库（14 模块）

| 模块 | 职责 | 关键接口 |
|------|------|---------|
| unified_extractor.py | ★ 方案 C 统一抽取器：LLM 一步抽取 Entity+Relation+source_text，或 `--from-file` 吃标注 JSON；后处理（Evidence 包装/ID 分配/词典标准化）+ P7 校验 + 缓存；`_extract_single` 调 `select_profile` 选 profile | `python -m pipeline.unified_extractor <doc> [--force\|--validate\|--from-file f --annotator x]` |
| llm_client.py | OpenAI 兼容客户端（httpx、JSON 模式、.env、重试分类、推理模型兼容） | `LLMClient.from_env()`；`python -m pipeline.llm_client` 连通性测试 |
| markdown_reader.py | OCR Markdown 读取：file_index.csv → .md，从 content_list_v2.json 重建 `<!-- page: N printed: M -->` 页码 marker（重建 <50% 回退原文） | `MarkdownReaderImpl(root).read(doc_id) -> (text, path)` |
| page_marker.py | 页码 marker 唯一解析入口（PAGE_MARKER_RE / PAGE_NUM_RE / extract_pdf_page / extract_printed_page / strip_page_markers） | 所有下游脚本统一 import，禁止自带正则 |
| source_locator.py | 引文定位：normalize（NFC+引号破折号等价+剥 marker+OCR 噪声+空白折叠+小写，**不做**缩写展开）、SourceIndex（locate/locate_span/pages_of）、contains_phrase | 质检门与页码校验共用同一套归一化 |
| qc_patterns.py | 句式级疑点判据（方法句/能力句/引文句/ASSESSED_BY tail/IMPROVES 语义/统计量实体/截断引文），RESULT_VERB_RE 等词表 | `relation_review_tags` / `entity_review_tags` / `citation_truncated_after` |
| prompts/disease_profiles.py | ★ 疾病系路由：按 `document_id` 前缀选择 `DiseaseProfile`，6 个差异段（entity_examples / high_freq_entities / relation_patterns / classification_hints / assessment_scales / example_output）由 `build_system_prompt` 注入 | `select_profile(document_id) → DiseaseProfile`；`BT_PROFILE` / `CV_PROFILE` / `NL_PROFILE` / `PS_PROFILE` / `DEFAULT_PROFILE` |
| prompts/unified_prompt.py | ★ 统一抽取 Prompt（17 entity_type + 22 relation_type + 9 assertion_type + 必填字段常量）；`build_system_prompt(profile)` 接收 profile 参数注入疾病系差异段，共享段不变 | `ENTITY_TYPES` / `RELATION_TYPES` / `ASSERTION_TYPES` / `DOMAIN_RANGE` / `build_system_prompt(profile=DiseaseProfile)` |
| prompts/entity_prompt.py, relation_prompt.py | 旧三阶段 Prompt（枚举常量仍被引用，保留） | — |
| id_generator.py | 确定性 ID 生成 + 去重语义（§2 ID 规则） | make_evidence_id / make_entity_id / make_relation_id |
| entity_normalizer.py | 词典标准化：6 类词典精确/忽略大小写匹配 → canonical_name/ontology_id，无匹配置 null（不做模糊匹配） | `python -m pipeline.entity_normalizer <doc>` |
| json_schema_validator.py | P7 结构校验（schemas/*.schema.json，required/类型/枚举/additionalProperties） | validate(instance, schema_name) |
| rule_validator.py | P7 业务校验：存在性/文献一致性/Domain-Range/RECOMMENDED_BY 拦截(D-5)/自环/唯一性 | validate(evidences, entities, relations, doc_id) |
| cache_manager.py | 缓存路径：`data/extracted/{RUN_VERSION}/{doc}_{suffix}.json`，版本来自 .env RUN_VERSION 或从 LLM_MODEL 推导 | get_run_version / get_cache_path |
| metadata_provider.py | 元数据读取：document_metadata.csv 惰性加载，按 doc_id 返回行 dict | MetadataProviderImpl(root).get_metadata(doc_id) |
| state_manager.py | 文档状态机（PENDING→PROCESSING→SUCCESS/FAILED/RETRY/MANUAL_REVIEW）+ 检查点 + ErrorCode | 批量编排用 |
| single_doc_runner.py | 单文档流水线编排框架（9 个 Protocol：Reader/MetadataProvider/Extractor/Validator…），旧三阶段的编排壳 | `python -m pipeline.single_doc_runner <doc>`（自检 stub） |

> 旧三阶段抽取器（evidence/entity/relation_extractor + p4-p7_selfcheck + evidence_prompt）已归档
> `_archive/pipeline_old/`，unified_extractor 对其零依赖。

---

## 4. agent_generated/scripts/（标注路线，4 个）

### 4.1 check_agent_raw.py — 落盘前质检门

- **功能**：标注 raw JSON 进统一链路前的确定性检查。error = 必须修（编造文本/端点未登记/枚举/
  Domain-Range/自包含/页码/marker 单调/ImagingModality 误判）；复查队列 = 8 个 WARN tag 句式疑点。
- **输入**：`data/agent_generated/{doc}_unified.json` + `agent_generated/agent_input_v2/{doc}.md`
- **输出**：终端报告；`--json` 写 QA 报告（建议 `data/agent_generated/audits/qa_report.json`）
- **前置**：标注 JSON 已落盘；对应输入 Markdown 存在
- **命令**：

```bash
# 单篇
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe agent_generated/scripts/check_agent_raw.py --doc NL003342
# 全批 12 篇 + 写报告
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe agent_generated/scripts/check_agent_raw.py \
    --input-dir agent_generated/agent_input_v2 --json data/agent_generated/audits/qa_report.json
```

- **通过标准**：0 error；WARN 复查队列逐条人工判 `成立/应舍弃`，判定前不得据 tag 删数据。

### 4.2 batch_agent_gold.py — 批量进统一链路 + 指标表

- **功能**：逐篇把 `data/agent_generated/{doc}_unified.json` 送 `pipeline.unified_extractor --from-file`
  （后处理 + P7 + 缓存），再读缓存算指标（P7 阻断/§4.4 一致率/Domain-Range/逐字定位率/Negative 占比/
  canonical 命中率/page 溯源覆盖），产出分层指标表。指标全是**自洽性**指标，语义对错仍需人工。
- **输入**：`data/agent_generated/{doc}_unified.json`；抽样清单默认 `agent_generated/gold/stratified_sample_v3.json`
- **输出**：缓存 `data/extracted/{RUN_VERSION}/`；指标 `data/agent_generated/audits/stratified_metrics.{md,json}`
- **前置**：质检门 0 error；.env 已配置（RUN_VERSION 决定缓存目录）
- **命令**：

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe agent_generated/scripts/batch_agent_gold.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe agent_generated/scripts/batch_agent_gold.py --force          # 重跑覆盖缓存
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe agent_generated/scripts/batch_agent_gold.py --docs PS002110 BT000164
```

### 4.3 sample_agent_input.py — 分层抽样生成标注输入

- **功能**：从语料（metadata/first/file_index.csv × metadata/final/keep_true.csv）分层随机抽
  （CV/NL/PS/BT 四层，固定 seed 可复现），文本经 MarkdownReaderImpl 重建（与 API 路线同输入形式），
  窗口/类型/语言/CJK 比例卡口，拒绝逐条记账。
- **输入**：metadata/first/file_index.csv、metadata/final/keep_true.csv、results/ 下的 OCR 产出
- **输出**：清单 `agent_generated/gold/stratified_sample_v3.{json,md}`；`--copy` 时把输入写入 agent_input_v2/
- **命令**：

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe agent_generated/scripts/sample_agent_input.py --dry-run   # 只看不写
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe agent_generated/scripts/sample_agent_input.py --copy      # 生成并拷贝输入
```

### 4.4 build_audit_sheet.py — 人工审阅清单

- **功能**：从统一缓存生成逐条关系审阅表（三元组 + assertion + 页/章 + 正则疑点 + 原文全句），
  每篇随机抽 N 条（seed 固定）做精确率抽查，其余备查。
- **输入**：`data/extracted/{RUN_VERSION}/{doc}_unified.json`；抽样清单默认 `agent_generated/gold/stratified_sample_v3.json`
- **输出**：`--out` 指定的 Markdown 审阅清单
- **命令**：

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe agent_generated/scripts/build_audit_sheet.py \
    --run-version Agent-Gold-Strat12-v3 --sample 10 --out data/agent_generated/audits/strat12_v3_audit_sheet.md
```

---

## 5. scripts/（通用工具，4 个）

### 5.1 summarize_agent_outputs.py — 产出汇总 + 复查队列

- **功能**：给每份 `{doc}_unified.json` 开头写 `_summary`（实体/关系数、覆盖率、孤儿、断言分布、
  自包含/超长 mention/大小写重复等），并汇总 `SUMMARY.{md,json}` 到 `data/agent_generated/audits/`。
  复查队列与质检门共用 qc_patterns 判据。
- **输入**：`data/agent_generated/*_unified.json`（`--dir` 可改）
- **输出**：回写 `_summary` 到原文件 + `data/agent_generated/audits/SUMMARY.{md,json}`
- **命令**：

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe scripts/summarize_agent_outputs.py
```

### 5.2 batch_unified.py — API 路线批量抽取（方案 C）

- **功能**：逐篇调 `pipeline.unified_extractor`（LLM 路线），显示进度，输出对比表。
  读取 Markdown → 读取元数据 → 按 `document_id` 前缀 `select_profile` 选疾病系 profile →
  调用 LLM 抽取（system prompt 由 `build_system_prompt(profile)` 注入疾病系差异段）。
- **输入**：results/ OCR 产出 + metadata/first/document_metadata.csv；.env LLM 配置
- **输出**：`data/extracted/{RUN_VERSION}/{doc}_unified.json`
- **命令**：

```bash
.venv\Scripts\python.exe -m scripts.batch_unified BT000001 BT000002 --force
.venv\Scripts\python.exe -m scripts.batch_unified --all --force
```

### 5.3 build_dictionaries.py — 词典构建

- **功能**：扫描 Entity 缓存，LLM **保守**分组同义词（仅大小写/缩写全称/单复数/OCR 错误，
  不得凭医学常识合并），生成 6 类标准词典 CSV。
- **输入**：`data/extracted/{RUN_VERSION}/*_entity.json`（至少 1 个）
- **输出**：`dictionaries/{disease|anatomy|mri_sequence|imaging_finding|treatment|biomarker}_dictionary.csv`；
  LLM 草案缓存 `dictionaries/.cache/`
- **命令**：

```bash
python -m scripts.build_dictionaries --list     # 先查看可用数据
python -m scripts.build_dictionaries            # 构建 6 个词典
python -m scripts.build_dictionaries --force    # 覆盖 LLM 缓存重建
```

### 5.4 ensure_summary.py — 抽完即补 _summary

- **功能**：给单篇 raw JSON 在 `document_id` 之后插入 `_summary`（实体/关系数、覆盖率、孤儿数、
  entity_types / relation_types / assertion_types 分布），方便抽取后立刻肉眼查看数量。
  与 5.1 的区别：5.1 是批量汇总 + 写 SUMMARY 报告；5.4 是单篇即时补，抽取流水线每篇跑一次。
- **输入**：`data/agent_generated/{doc}_unified.json`
- **输出**：回写 `_summary` 到原文件（无破坏，保留 entities/relations 顺序）
- **命令**：

```bash
.venv\Scripts\python.exe scripts\ensure_summary.py NL003342      # 单篇
.venv\Scripts\python.exe scripts\ensure_summary.py --all        # 全批
```

---

## 6. metadata/ 三层 CSV

| 层 | 文件 | 说明 |
|----|------|------|
| first/ | file_index.csv | document_id → markdown_path 映射（markdown_reader 依赖） |
| first/ | document_metadata.csv | 全量元数据（title/journal/year/document_type/study_type/content_type…） |
| first/ | crossref_cache.json | 本地 CrossRef 缓存（仅限历史补抓结果；**规则禁止联网搜元数据**） |
| first/ | clinical_imaging_metadata.csv, evidence_metadata.csv | 上游采集层补充表 |
| filter/ | keep_true / keep_review / keep_false.csv | 相关性过滤层：按摘要双重命中（脑病+MRI 术语）+ 结构化章节 + 文档类型评分后三分类 |
| final/ | keep_true / keep_review / keep_false.csv | 人工审核后的最终层；**keep_true 含全部相关条目，排除 final_decision 列、带 note 列**（人工解释） |

抽样（sample_agent_input.py）以 `metadata/final/keep_true.csv` 为合格语料池。
历史备份链（*.bak.csv / *.dirty_bak.csv）已归档 `_archive/metadata_bak/`。

---

## 7. 环境配置（.env）

```env
# LLM 配置（必填三项；OpenAI 兼容端点均可）
LLM_API_KEY=sk-你的密钥
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash

# 运行版本目录名（抽取结果保存到 data/extracted/{RUN_VERSION}/）
# 换模型时改此值，旧版本数据保留可对比；不设则从 LLM_MODEL 自动推导
RUN_VERSION=DeepSeek-V4-Flash

# 可选：超时/输出 token/上下文窗口（llm_client.py 读取）
LLM_TIMEOUT=800          # 大文档（如 48K 字符）需加大，默认 300
LLM_MAX_TOKENS=16384     # 给输入 prompt 留空间；推理模型思考耗 token 需加大
LLM_MAX_CONTEXT=64000    # DeepSeek-V4-Flash=64000, Qwen2.5-7B=32768
```

- 优先级：构造参数 > 环境变量 > .env。
- **换模型流程**：改 LLM_MODEL + RUN_VERSION → `python -m pipeline.llm_client` 测连通 →
  重抽（新 RUN_VERSION 目录隔离）→ 需要时 `python -m scripts.build_dictionaries --force`。
- 依赖安装：`uv sync`（推荐）或 `pip install httpx pymupdf tqdm jsonschema`；虚拟环境 `.venv\Scripts\python.exe`。
- Windows 终端建议 `set PYTHONIOENCODING=utf-8`（中文输出防乱码）。

---

## 8. 常见任务速查

| 任务 | 命令 |
|------|------|
| 测 LLM 连通 | `python -m pipeline.llm_client` |
| API 路线单篇抽取 | `python -m pipeline.unified_extractor BT000001 --force` |
| 只重跑 P7 校验（不调 LLM） | `python -m pipeline.unified_extractor BT000001 --validate` |
| 标注 JSON 进链路（不调 LLM） | `python -m pipeline.unified_extractor BT000001 --from-file data\agent_generated\BT000001_unified.json --annotator Agent-v3` |
| 标注质检 | `python agent_generated/scripts/check_agent_raw.py --doc BT000001` |
| Entity 标准化测试 | `python -m pipeline.entity_normalizer BT000001` |
| 读重建 Markdown 冒烟 | 见 markdown_reader.py docstring（`MarkdownReaderImpl(Path('.')).read('BT000001')`） |
| 生成新一批标注输入 | `python agent_generated/scripts/sample_agent_input.py --copy` |
| 全链路批量（标注路线） | `python agent_generated/scripts/batch_agent_gold.py` |
| 汇总报告 | `python scripts/summarize_agent_outputs.py` |
| 补单篇 _summary（抽完即跑） | `python scripts/ensure_summary.py <doc_id>` |
| 查疾病系 profile 路由 | `python -c "from pipeline.prompts.disease_profiles import select_profile; print(select_profile('BT000008').name)"` |
| 人工审阅清单 | 见 §4.4 |

> 疾病系路由函数：`select_profile(document_id) → DiseaseProfile`
> （`pipeline/prompts/disease_profiles.py`）。前缀映射：BT→脑肿瘤、CV→脑血管、NL→神经内科、PS→精神类、其他→通用。

---

## 9. 维护约定

1. **归档即回退点**：任何被取代的脚本/数据进 `_archive/` 对应子目录，不直接删除。
   文档版本化同理：v1 归档于 `docs/v1/`，当前版本在 `docs/v2/`。
2. **判据单一来源**：句式疑点正则只在 pipeline/qc_patterns.py；页码 marker 正则只在 pipeline/page_marker.py；
   归一化只在 pipeline/source_locator.py；疾病系路由只在 pipeline/prompts/disease_profiles.py。
   其余脚本 import，禁止复制。
3. **脚本注释与功能同步**：改行为必须同步 docstring 与本文档。
4. **契约只读**：Schema_rule/ 与 schemas/ 不可修改；枚举扩展需走契约变更流程。
5. **质检门先于链路**：标注 JSON 必须先过 check_agent_raw.py（0 error）再进 batch_agent_gold.py。
6. **疾病系专属内容分离**：共享规则在 `docs/v2/AGENT_INSTRUCTION.md`，疾病系专属内容在
   `docs/v2/disease_*.md`；管线侧差异段由 `disease_profiles.py` 提供，`unified_prompt.build_system_prompt` 注入。
