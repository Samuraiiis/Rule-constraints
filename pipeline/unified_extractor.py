"""统一抽取器（方案 C）：一步抽取 Entity + Relation，Python 后处理包装 Evidence。

替代三阶段串行设计（P4 Evidence → P5 Entity → P6 Relation）的根本问题：
    Evidence 预抽取太保守 → Entity 找不到合法 evidence_id → 被丢弃
    → Relation 找不到合法 head/tail_entity_id → 被丢弃
    级联误差放大，实测 BT000008: 25 ENT → 1 REL。

方案 C 流程：
    1. 一次 LLM 调用生成 {entities, relations}，每条带 source_text
    2. Python 后处理：
       a. 收集所有 source_text → 去重 → 包装成 Evidence 草稿 → assign_evidence_ids
       b. 为每个 entity 匹配 evidence_id（通过 source_text）→ assign_entity_ids
          → EntityNormalizer 词典标准化（填 canonical_name / ontology_id）
       c. 为每个 relation 匹配 head/tail entity_id（通过 mention+type）→ assign_relation_ids
       d. backfill_evidence_entities（反向关联）
    3. 输出统一格式 {evidences, entities, relations}
    4. validate_result()：P7 校验（JSON Schema + Rule-based），调用方显式执行

职责：
    LLM    ：发现实体和关系（带原文 source_text）
    Python ：ID 生成、source_text→Evidence 包装、mention→entity_id 匹配、反向回填
    本模块 ：编排上述步骤 + 重试 + 校验 + 缓存

命令示例：
    python -m pipeline.unified_extractor BT000008          # 读取或抽取
    python -m pipeline.unified_extractor BT000008 --force  # 强制重新抽取

前置条件：
    - .env 配置了 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
    - metadata/first/file_index.csv 存在
    - 对应 Markdown 文件存在
"""
from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pipeline.cache_manager import ensure_dir, get_cache_path, get_run_version
from pipeline.entity_normalizer import EntityNormalizerImpl
from pipeline.json_schema_validator import JSONSchemaValidatorImpl
from pipeline.llm_client import LLMClient, LLMError
from pipeline.page_marker import is_page_marker, split_with_markers
from pipeline.prompts.unified_prompt import (
    ENTITY_REQUIRED_FIELDS,
    RELATION_REQUIRED_FIELDS,
    build_retry_message,
    build_system_prompt,
    build_user_prompt,
)
from pipeline.prompts.disease_profiles import select_profile
from pipeline.prompts.entity_prompt import ENTITY_TYPES
from pipeline.prompts.relation_prompt import (
    ASSERTION_TYPES,
    DISALLOWED_FOR_LLM,
    RELATION_TYPES,
)
from pipeline.rule_validator import RuleValidatorImpl
from pipeline.single_doc_runner import (
    ExtractionError,
    ValidationIssue,
    _BLOCKING_ERRORS,
    assign_entity_ids,
    assign_evidence_ids,
    assign_relation_ids,
    backfill_evidence_entities,
)
from pipeline.state_manager import ErrorCode
from pipeline.single_doc_runner import severity_for

from agent_generated.scripts.check_agent_raw import DocReport, check as check_agent_raw

# P7 校验器（无状态，模块级复用）
_JSON_VALIDATOR: Final[JSONSchemaValidatorImpl] = JSONSchemaValidatorImpl()
# 模块级校验器（strict_other=True，自动抽取模式下拦截 OTHER 关系）
# 人工审核流程需单独创建 RuleValidatorImpl(strict_other=False)，不在自动管线中使用
_RULE_VALIDATOR: Final[RuleValidatorImpl] = RuleValidatorImpl(strict_other=True)

# 合法枚举集合（用于快速校验）
_VALID_ENTITY_TYPES: Final[frozenset[str]] = frozenset(ENTITY_TYPES)
_VALID_RELATION_TYPES: Final[frozenset[str]] = frozenset(RELATION_TYPES)
_VALID_ASSERTION_TYPES: Final[frozenset[str]] = frozenset(ASSERTION_TYPES)
_DISALLOWED: Final[frozenset[str]] = frozenset(DISALLOWED_FOR_LLM)

# 默认重试次数
DEFAULT_MAX_RETRIES: Final[int] = 3

# Evidence 类型提示（Python 后处理推断用，简化版：根据 entity/relation 类型推断）
_EVIDENCE_TYPE_MAP: Final[dict[str, str]] = {
    "ImagingFinding": "Imaging Finding",
    "ClinicalFeature": "Clinical Finding",
    "Technical Finding": "Technical Finding",
    "Pathology": "Pathology Finding",
    "GeneticFeature": "Genetic Finding",
    "MolecularFeature": "Molecular Finding",
    "StudyPopulation": "Study Population",
    "Disease": "Clinical Finding",
    "Treatment": "Treatment Outcome",
}


# --------------------------------------------------------------------------- #
# 三层数据保留边界
# --------------------------------------------------------------------------- #
@dataclass
class ExtractionResult:
    """抽取结果，显式保留 raw（解析后、后处理前）和 processed（后处理后）三层边界。

    Layer 1: raw_response — LLM 原始响应文本 或 Agent JSON 字符串
    Layer 2: raw_entities / raw_relations — 解析后、_post_process 前的数据
    Layer 3: processed — _post_process 后的 {evidences, entities, relations}
    """

    document_id: str
    raw_response: str           # Layer 1
    raw_entities: list[dict]    # Layer 2
    raw_relations: list[dict]   # Layer 2
    processed: dict[str, list]  # Layer 3: {evidences, entities, relations}
    metadata: dict = field(default_factory=dict)


@dataclass
class FullValidationResult:
    """两阶段（阶段一原始质检 + 阶段二结构校验）合并后的完整校验结果。

    has_blocking 基于所有阶段合并后的 severity == "ERROR" 计算，
    不只检查阶段一报告。validation_incomplete=True 时表示阶段一被跳过，
    不能将"未执行的检查"计作"检查通过"。
    """

    stage1_report: "DocReport | None"      # 阶段一原始报告（check_agent_raw）
    stage2_issues: list[ValidationIssue]    # 阶段二 P7 校验
    stage1_issues: list[ValidationIssue]    # 阶段一转换后
    all_issues: list[ValidationIssue]       # 合并后全部
    error_count: int = 0                    # ERROR 级别
    warn_count: int = 0                     # WARN 级别
    review_count: int = 0                   # REVIEW 级别
    has_blocking: bool = False              # 基于 all_issues 中 ERROR 计算
    stage1_status: str = "completed"        # "completed" / "skipped_markdown_not_found"
    validation_incomplete: bool = False     # 阶段一被跳过时为 True

    def fingerprint_set(self) -> set[tuple]:
        """稳定指纹集合，用于 --apply 前后比较（不依赖 message 文字）。

        指纹 = (error_code/error_type, field, ref_id)。
        """
        return {i.fingerprint() for i in self.all_issues}


# --------------------------------------------------------------------------- #
# 适配层：check_agent_raw DocReport → ValidationIssue 转换
# --------------------------------------------------------------------------- #
# error_type（check_agent_raw）→ ErrorCode 映射
_ERROR_TYPE_TO_ERROR_CODE: Final[dict[str, ErrorCode]] = {
    "source_text_not_found": ErrorCode.SOURCE_TEXT_MISSING,
    "mention_not_in_source": ErrorCode.SOURCE_TEXT_MISSING,
    "page_mismatch": ErrorCode.SCHEMA_VALIDATION_FAILED,
    "page_type_error": ErrorCode.SCHEMA_VALIDATION_FAILED,
    "marker_format_error": ErrorCode.SCHEMA_VALIDATION_FAILED,
    "marker_non_monotonic": ErrorCode.SCHEMA_VALIDATION_FAILED,
    "endpoint_not_registered": ErrorCode.ENTITY_NOT_FOUND,
    "endpoint_case_mismatch": ErrorCode.ENTITY_NOT_FOUND,
    "invalid_enum": ErrorCode.INVALID_ENUM,
    "disallowed_relation": ErrorCode.UNSUPPORTED_RELATION,
    "self_contained": ErrorCode.DOMAIN_RANGE_MISMATCH,
    "imaging_modality_misjudge": ErrorCode.SCHEMA_VALIDATION_FAILED,
    "missing_field": ErrorCode.MISSING_REQUIRED_FIELD,
    "domain_range_violation": ErrorCode.DOMAIN_RANGE_MISMATCH,
}


def _convert_doc_report(rep: DocReport) -> list[ValidationIssue]:
    """适配层：把 check_agent_raw 的 DocReport 转换为 ValidationIssue 列表。

    check_agent_raw 只返回自身的检查报告，本函数完成 error_type → ErrorCode、
    severity 透传。避免 check_agent_raw 依赖 unified_extractor（防循环导入）。
    """
    issues: list[ValidationIssue] = []
    for err in rep.errors:
        code = _ERROR_TYPE_TO_ERROR_CODE.get(err.error_type, ErrorCode.SCHEMA_VALIDATION_FAILED)
        issues.append(ValidationIssue(
            error_code=code,
            message=err.message,
            field=err.field,
            ref_id=err.ref_id,
            severity=err.severity,
        ))
    return issues


def run_full_validation(
    document_id: str,
    result: ExtractionResult,
    markdown_path: Path | None,
) -> FullValidationResult:
    """两阶段校验编排：阶段一原始质检 + 阶段二结构校验。

    阶段一：check_agent_raw 检查 Layer 2 数据（raw_entities/raw_relations）
            和对应 Markdown 原文。即使发现阻断错误也继续执行阶段二，生成完整诊断。
    阶段二：validate_result 检查 Layer 3 数据（processed）。
    合并后基于 severity == "ERROR" 计算 has_blocking。

    markdown_path 为 None 或文件不存在时，阶段一被跳过（标记为 incomplete）。
    """
    # ---- 阶段一：原始数据质检 ----
    stage1_report: DocReport | None = None
    stage1_issues: list[ValidationIssue] = []
    stage1_status = "completed"
    validation_incomplete = False

    if markdown_path is not None and markdown_path.exists():
        raw_obj = {"entities": result.raw_entities, "relations": result.raw_relations}
        stage1_report = check_agent_raw(document_id, raw_obj, markdown_path)
        stage1_issues = _convert_doc_report(stage1_report)
    else:
        stage1_status = "skipped_markdown_not_found"
        validation_incomplete = True

    # ---- 阶段二：结构化后处理后校验 ----
    stage2_issues = validate_result(document_id, result.processed)

    # ---- 合并 ----
    all_issues = stage1_issues + stage2_issues
    error_count = sum(1 for i in all_issues if i.severity == "ERROR")
    warn_count = sum(1 for i in all_issues if i.severity == "WARN")
    review_count = sum(1 for i in all_issues if i.severity == "REVIEW")
    has_blocking = error_count > 0

    return FullValidationResult(
        stage1_report=stage1_report,
        stage2_issues=stage2_issues,
        stage1_issues=stage1_issues,
        all_issues=all_issues,
        error_count=error_count,
        warn_count=warn_count,
        review_count=review_count,
        has_blocking=has_blocking,
        stage1_status=stage1_status,
        validation_incomplete=validation_incomplete,
    )


class UnifiedExtractorImpl:
    """统一抽取器：一步抽取 Entity + Relation，Python 后处理包装 Evidence。

    构造参数：
        llm_client   LLMClient 实例（已配置 api_key / base_url / model）
        max_retries  LLM 输出错误时的最大重试次数（默认 3）
        normalizer   EntityNormalizer 实例（默认加载 dictionaries/）
    """

    def __init__(
        self,
        llm_client: LLMClient,
        max_retries: int = DEFAULT_MAX_RETRIES,
        normalizer: EntityNormalizerImpl | None = None,
    ) -> None:
        self.llm = llm_client
        self.max_retries = max_retries
        self.normalizer = normalizer or EntityNormalizerImpl()

    # 分块阈值：超过此字符数则自动分块（约 7K tokens，留足输出空间）
    CHUNK_THRESHOLD: Final[int] = 25_000
    # 分块目标大小：每块约 20K 字符（含页码标记）
    CHUNK_TARGET: Final[int] = 20_000

    def extract(
        self,
        document_id: str,
        markdown: str,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """一步抽取 Entity + Relation，返回 ExtractionResult（含三层边界）。

        大文档（> CHUNK_THRESHOLD 字符）自动分块抽取后合并：
            1. 按页码标记切分为多个 chunk
            2. 每个 chunk 独立调 LLM 抽取
            3. 合并所有 chunk 的 entities_raw + relations_raw
            4. Python 后处理（assign_*_ids 自动去重合并）

        参数：
            document_id  文献 ID
            markdown     MinerU OCR Markdown 文本
            metadata     文献元数据 dict（可选，默认空 dict）

        返回：
            ExtractionResult，其中：
              raw_response   Layer 1: LLM 原始响应文本
              raw_entities   Layer 2: 解析后、_post_process 前的实体
              raw_relations  Layer 2: 解析后、_post_process 前的关系
              processed      Layer 3: {evidences, entities, relations}（后处理后）
        """
        if metadata is None:
            metadata = {}

        # 判断是否需要分块
        if len(markdown) <= self.CHUNK_THRESHOLD:
            # 小文档：单次抽取
            entities_raw, relations_raw, raw_response = self._extract_single(
                document_id, markdown, metadata
            )
        else:
            # 大文档：分块抽取后合并
            chunks = self._chunk_markdown(markdown)
            print(f"  📄 文档过大（{len(markdown)} 字符），分块为 {len(chunks)} 块")
            all_entities: list[dict[str, Any]] = []
            all_relations: list[dict[str, Any]] = []
            all_raw_responses: list[str] = []
            for ci, chunk in enumerate(chunks, 1):
                print(f"  [chunk {ci}/{len(chunks)}] ({len(chunk)} 字符)")
                try:
                    ent_chunk, rel_chunk, raw_resp = self._extract_single(
                        document_id, chunk, metadata
                    )
                    all_entities.extend(ent_chunk)
                    all_relations.extend(rel_chunk)
                    all_raw_responses.append(raw_resp)
                    print(f"    → ENT={len(ent_chunk)} REL={len(rel_chunk)}")
                except ExtractionError as exc:
                    print(f"    ⚠ chunk {ci} 失败: {exc}（跳过）")
            entities_raw = all_entities
            relations_raw = all_relations
            raw_response = "\n---\n".join(all_raw_responses) if all_raw_responses else ""
            print(f"  合并后: ENT={len(entities_raw)} REL={len(relations_raw)}")

        # 深拷贝 raw 数据，防止 _post_process 就地修改污染 Layer 2 边界
        raw_entities_snapshot = copy.deepcopy(entities_raw)
        raw_relations_snapshot = copy.deepcopy(relations_raw)

        # Python 后处理（操作 entities_raw / relations_raw 副本）
        processed = self._post_process(document_id, entities_raw, relations_raw)

        return ExtractionResult(
            document_id=document_id,
            raw_response=raw_response,
            raw_entities=raw_entities_snapshot,
            raw_relations=raw_relations_snapshot,
            processed=processed,
            metadata=metadata,
        )

    def _extract_single(
        self,
        document_id: str,
        markdown: str,
        metadata: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        """单次 LLM 调用抽取（含重试），返回 (entities_raw, relations_raw, raw_response)。"""
        profile = select_profile(document_id)
        system_prompt = build_system_prompt(profile)
        user_prompt = build_user_prompt(metadata, markdown)

        last_error_feedback: str | None = None
        last_raw_response: str = ""

        for attempt in range(1, self.max_retries + 1):
            messages = self._build_messages(
                system_prompt, user_prompt, last_error_feedback, last_raw_response
            )

            try:
                raw = self.llm.chat_json(messages)
            except LLMError as exc:
                raise ExtractionError(
                    ErrorCode.INVALID_JSON,
                    f"LLM 调用失败（attempt {attempt}）: {exc}",
                ) from exc

            last_raw_response = raw

            try:
                entities_raw, relations_raw = self._parse_and_validate(raw)
            except _ValidationError as exc:
                last_error_feedback = exc.feedback
                if attempt < self.max_retries:
                    continue
                raise ExtractionError(
                    exc.error_code,
                    f"重试 {self.max_retries} 次后仍失败: {exc.feedback}",
                ) from exc

            return entities_raw, relations_raw, last_raw_response

        raise ExtractionError(
            ErrorCode.INVALID_JSON,
            "未知错误：重试循环异常退出",
        )

    def _chunk_markdown(self, markdown: str) -> list[str]:
        """按页码标记切分 Markdown，返回 chunk 列表。

        切分策略（保证不截断句子）：
            1. 按 `<!-- page: N [printed: M] -->` 标记切分为页面段落
            2. 累积到 CHUNK_TARGET 字符时，在最近的段落/行边界切分
            3. 每个 chunk 保留页码标记，保持上下文完整
            4. 如果单页超过 CHUNK_TARGET，在段落边界（空行）切分
        """
        import re

        # 按 page 标记切分为页面段
        page_parts = split_with_markers(markdown)

        # 重组为 (page_marker, page_content) 对
        pages: list[str] = []
        current_page: list[str] = []
        for part in page_parts:
            current_page.append(part)
            # 检测到下一个 page 标记时，当前页结束
            if is_page_marker(part) and len(current_page) > 1:
                pages.append("".join(current_page[:-1]))
                current_page = [part]
        if current_page:
            pages.append("".join(current_page))

        # 累积页面到 CHUNK_TARGET，在页面边界切分
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for page in pages:
            # 如果单页就超过 CHUNK_TARGET，在段落边界（空行）切分
            if len(page) > self.CHUNK_TARGET:
                # 先把已累积的 flush
                if current:
                    chunks.append("".join(current))
                    current = []
                    current_len = 0
                # 按空行切分大页面
                paragraphs = re.split(r"\n\s*\n", page)
                para_chunk: list[str] = []
                para_len = 0
                for para in paragraphs:
                    para_chunk.append(para)
                    para_len += len(para) + 2  # +2 for \n\n
                    if para_len >= self.CHUNK_TARGET:
                        chunks.append("\n\n".join(para_chunk))
                        para_chunk = []
                        para_len = 0
                if para_chunk:
                    leftover = "\n\n".join(para_chunk)
                    if chunks and len(leftover) < self.CHUNK_TARGET // 3:
                        chunks[-1] += "\n\n" + leftover
                    else:
                        chunks.append(leftover)
                continue

            # 正常累积
            if current_len + len(page) > self.CHUNK_TARGET * 1.2:
                # 超过 120% 阈值，切分
                chunks.append("".join(current))
                current = [page]
                current_len = len(page)
            else:
                current.append(page)
                current_len += len(page)

        if current:
            remainder = "".join(current)
            if chunks and len(remainder) < self.CHUNK_TARGET // 3:
                chunks[-1] += remainder
            else:
                chunks.append(remainder)

        return chunks if chunks else [markdown]

    # -- messages 构建 ------------------------------------------------------ #
    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        error_feedback: str | None,
        last_raw_response: str,
    ) -> list[dict[str, str]]:
        """构建 OpenAI chat messages。

        首次：system + user。
        重试：system + user + assistant(上次响应) + user(纠正提示)。
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if error_feedback and last_raw_response:
            messages.append({"role": "assistant", "content": last_raw_response})
            messages.append(
                {"role": "user", "content": build_retry_message(error_feedback, last_raw_response)}
            )

        return messages

    # -- 解析 + 校验 -------------------------------------------------------- #
    def _parse_and_validate(
        self,
        raw: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """解析 LLM 响应为 (entities_raw, relations_raw)，做轻量校验。

        校验项（P7 才做完整 JSON Schema 校验）：
            1. JSON 合法
            2. 顶层有 entities 和 relations 数组
            3. 每条 entity 含必填字段 + entity_type 枚举合法
            4. 每条 relation 含必填字段 + 枚举合法
            5. relation 的 head/tail_mention 非空
            6. source_text 非空
            7. 不含禁用的 relation_type（RECOMMENDED_BY / OTHER）

        失败时抛 _ValidationError（含 error_code + feedback 供重试）。
        """
        # 提取 JSON（兼容推理模型的 think 标签包裹）；静态方法，外部标注文件同样适用
        json_str = LLMClient._extract_json_from_content(raw)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise _ValidationError(
                ErrorCode.INVALID_JSON,
                f"INVALID_JSON: 返回的不是合法 JSON（{exc.msg}）",
            ) from exc

        if not isinstance(data, dict):
            raise _ValidationError(
                ErrorCode.INVALID_JSON,
                "INVALID_JSON: 顶层不是 JSON 对象",
            )

        # 提取 entities 和 relations
        entities_raw = data.get("entities")
        relations_raw = data.get("relations")

        if entities_raw is None:
            raise _ValidationError(
                ErrorCode.MISSING_REQUIRED_FIELD,
                "MISSING_REQUIRED_FIELD: 缺少 entities 字段",
            )
        if relations_raw is None:
            raise _ValidationError(
                ErrorCode.MISSING_REQUIRED_FIELD,
                "MISSING_REQUIRED_FIELD: 缺少 relations 字段",
            )
        if not isinstance(entities_raw, list):
            raise _ValidationError(
                ErrorCode.INVALID_JSON,
                "INVALID_JSON: entities 不是数组",
            )
        if not isinstance(relations_raw, list):
            raise _ValidationError(
                ErrorCode.INVALID_JSON,
                "INVALID_JSON: relations 不是数组",
            )

        # 校验 entities
        valid_mentions: set[str] = set()  # 收集合法 mention 供 relation 校验
        for i, ent in enumerate(entities_raw):
            if not isinstance(ent, dict):
                raise _ValidationError(
                    ErrorCode.INVALID_JSON,
                    f"INVALID_JSON: entities[{i}] 不是 JSON 对象",
                )

            # 必填字段
            for field in ENTITY_REQUIRED_FIELDS:
                if field not in ent:
                    raise _ValidationError(
                        ErrorCode.MISSING_REQUIRED_FIELD,
                        f"MISSING_REQUIRED_FIELD: entities[{i}].{field} 缺失",
                    )

            # entity_type 枚举
            etype = ent.get("entity_type", "")
            if etype not in _VALID_ENTITY_TYPES:
                raise _ValidationError(
                    ErrorCode.INVALID_ENUM,
                    f"INVALID_ENUM: entities[{i}].entity_type = '{etype}'，不在允许值中",
                )

            # mention 非空
            mention = ent.get("mention", "")
            if not mention or not str(mention).strip():
                raise _ValidationError(
                    ErrorCode.MISSING_REQUIRED_FIELD,
                    f"MISSING_REQUIRED_FIELD: entities[{i}].mention 为空",
                )

            # source_text 非空
            src = ent.get("source_text", "")
            if not src or not str(src).strip():
                raise _ValidationError(
                    ErrorCode.SOURCE_TEXT_MISSING,
                    f"SOURCE_TEXT_MISSING: entities[{i}].source_text 为空",
                )

            # 确保可选字段存在（page/section 可为 null）
            ent.setdefault("page", None)
            ent.setdefault("section", None)

            valid_mentions.add(str(mention).strip())

        # 校验 relations
        for i, rel in enumerate(relations_raw):
            if not isinstance(rel, dict):
                raise _ValidationError(
                    ErrorCode.INVALID_JSON,
                    f"INVALID_JSON: relations[{i}] 不是 JSON 对象",
                )

            # 必填字段
            for field in RELATION_REQUIRED_FIELDS:
                if field not in rel:
                    raise _ValidationError(
                        ErrorCode.MISSING_REQUIRED_FIELD,
                        f"MISSING_REQUIRED_FIELD: relations[{i}].{field} 缺失",
                    )

            # relation_type 枚举
            rtype = rel.get("relation_type", "")
            if rtype not in _VALID_RELATION_TYPES:
                raise _ValidationError(
                    ErrorCode.INVALID_ENUM,
                    f"INVALID_ENUM: relations[{i}].relation_type = '{rtype}'，不在允许值中",
                )

            # V1 禁用的 relation_type
            if rtype in _DISALLOWED:
                raise _ValidationError(
                    ErrorCode.INVALID_ENUM,
                    f"INVALID_ENUM: relations[{i}].relation_type = '{rtype}'，V1 禁止 LLM 生成",
                )

            # assertion_type 枚举
            atype = rel.get("assertion_type", "")
            if atype not in _VALID_ASSERTION_TYPES:
                raise _ValidationError(
                    ErrorCode.INVALID_ENUM,
                    f"INVALID_ENUM: relations[{i}].assertion_type = '{atype}'，不在允许值中",
                )

            # head/tail entity_type 枚举
            head_type = rel.get("head_entity_type", "")
            if head_type not in _VALID_ENTITY_TYPES:
                raise _ValidationError(
                    ErrorCode.INVALID_ENUM,
                    f"INVALID_ENUM: relations[{i}].head_entity_type = '{head_type}'，不在允许值中",
                )
            tail_type = rel.get("tail_entity_type", "")
            if tail_type not in _VALID_ENTITY_TYPES:
                raise _ValidationError(
                    ErrorCode.INVALID_ENUM,
                    f"INVALID_ENUM: relations[{i}].tail_entity_type = '{tail_type}'，不在允许值中",
                )

            # head/tail mention 非空
            head_mention = rel.get("head_mention", "")
            tail_mention = rel.get("tail_mention", "")
            if not head_mention or not str(head_mention).strip():
                raise _ValidationError(
                    ErrorCode.MISSING_REQUIRED_FIELD,
                    f"MISSING_REQUIRED_FIELD: relations[{i}].head_mention 为空",
                )
            if not tail_mention or not str(tail_mention).strip():
                raise _ValidationError(
                    ErrorCode.MISSING_REQUIRED_FIELD,
                    f"MISSING_REQUIRED_FIELD: relations[{i}].tail_mention 为空",
                )

            # head/tail mention 应在 entities 列表中（警告但不强制失败，
            # 因为 LLM 可能对 mention 做了轻微改写）
            # 注意：这里只记录，不阻断——后处理时做匹配

            # source_text 非空
            src = rel.get("source_text", "")
            if not src or not str(src).strip():
                raise _ValidationError(
                    ErrorCode.SOURCE_TEXT_MISSING,
                    f"SOURCE_TEXT_MISSING: relations[{i}].source_text 为空",
                )

            # 确保可选字段存在
            rel.setdefault("page", None)
            rel.setdefault("section", None)

        return entities_raw, relations_raw

    # -- Python 后处理：source_text → Evidence，mention → entity_id 匹配 ------- #
    def _post_process(
        self,
        document_id: str,
        entities_raw: list[dict[str, Any]],
        relations_raw: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Python 后处理：包装 Evidence + 匹配 entity_id + 反向回填。

        流程：
            1. 收集所有 source_text → 去重 → 构建 Evidence 草稿 → assign_evidence_ids
            2. 为每个 entity 匹配 evidence_id（通过 source_text）→ assign_entity_ids
               → EntityNormalizer 词典标准化（填 canonical_name / ontology_id）
            3. 为每个 relation 匹配 head/tail entity_id（通过 mention+type）
               + 匹配 evidence_id（通过 source_text）
               → assign_relation_ids
            4. backfill_evidence_entities（反向关联）
        """
        # Step 1: 收集所有 source_text，去重，构建 Evidence 草稿
        # 同时记录 source_text → evidence 草稿的映射
        seen_source_texts: dict[str, dict[str, Any]] = {}  # source_text → evidence_draft

        for ent in entities_raw:
            src = str(ent.get("source_text", "")).strip()
            if src and src not in seen_source_texts:
                seen_source_texts[src] = self._build_evidence_draft(
                    src, ent.get("section"), ent.get("page")
                )

        for rel in relations_raw:
            src = str(rel.get("source_text", "")).strip()
            if src and src not in seen_source_texts:
                seen_source_texts[src] = self._build_evidence_draft(
                    src, rel.get("section"), rel.get("page")
                )

        # 构建 Evidence 草稿列表（保持插入顺序）
        evidence_drafts = list(seen_source_texts.values())

        # 分配 evidence_id（assign_evidence_ids 会做同 source_text 去重）
        evidences = assign_evidence_ids(document_id, evidence_drafts)

        # 构建 source_text → evidence_id 映射
        src_to_ev_id: dict[str, str] = {}
        for ev in evidences:
            src = str(ev.get("source_text", "")).strip()
            if src:
                src_to_ev_id[src] = ev["evidence_id"]

        # Step 2: 为每个 entity 匹配 evidence_id → assign_entity_ids
        for ent in entities_raw:
            src = str(ent.get("source_text", "")).strip()
            ev_id = src_to_ev_id.get(src)
            if ev_id:
                ent["evidence_ids"] = [ev_id]
            else:
                # source_text 不在映射中（不应该发生，但防御性处理）
                ent["evidence_ids"] = []
        entities = assign_entity_ids(document_id, entities_raw)
        # Entity_schema §9：canonical_name / ontology_id 只能由词典赋写
        entities = [self.normalizer.normalize(e, document_id) for e in entities]

        # 构建 (mention_stripped, entity_type) → entity_id 映射
        mention_type_to_ent_id: dict[tuple[str, str], str] = {}
        for ent in entities:
            mention = str(ent.get("mention", "")).strip()
            etype = str(ent.get("entity_type", ""))
            mention_type_to_ent_id[(mention, etype)] = ent["entity_id"]

        # Step 3: 为每个 relation 匹配 head/tail entity_id + evidence_id
        relation_drafts: list[dict[str, Any]] = []
        matched_count = 0
        unmatched_relations: list[dict[str, Any]] = []

        for rel in relations_raw:
            head_mention = str(rel.get("head_mention", "")).strip()
            head_type = str(rel.get("head_entity_type", ""))
            tail_mention = str(rel.get("tail_mention", "")).strip()
            tail_type = str(rel.get("tail_entity_type", ""))
            src = str(rel.get("source_text", "")).strip()

            head_ent_id = mention_type_to_ent_id.get((head_mention, head_type))
            tail_ent_id = mention_type_to_ent_id.get((tail_mention, tail_type))
            ev_id = src_to_ev_id.get(src)

            if not head_ent_id or not tail_ent_id:
                # mention+type 匹配失败，尝试模糊匹配（mention 包含关系）
                head_ent_id = head_ent_id or self._fuzzy_match_mention(
                    head_mention, head_type, mention_type_to_ent_id
                )
                tail_ent_id = tail_ent_id or self._fuzzy_match_mention(
                    tail_mention, tail_type, mention_type_to_ent_id
                )

            if not head_ent_id or not tail_ent_id:
                # 仍匹配失败，跳过该 relation（记录但不入库）
                unmatched_relations.append(rel)
                continue

            relation_draft = {
                "head_entity_id": head_ent_id,
                "tail_entity_id": tail_ent_id,
                "relation_type": rel.get("relation_type"),
                "assertion_type": rel.get("assertion_type"),
                # Relation 不携带 source_text/page/section：relation.schema.json
                # additionalProperties=false，溯源统一通过 evidence_ids 指向 Evidence
                "evidence_ids": [ev_id] if ev_id else [],
            }
            relation_drafts.append(relation_draft)
            matched_count += 1

        if unmatched_relations:
            print(
                f"  ⚠ {len(unmatched_relations)} 条 Relation 无法匹配 head/tail entity_id（mention 不一致），已跳过"
            )
            for ur in unmatched_relations[:3]:
                print(
                    f"    head={ur.get('head_mention','')[:30]} "
                    f"tail={ur.get('tail_mention','')[:30]} "
                    f"type={ur.get('relation_type','')}"
                )

        relations = assign_relation_ids(document_id, relation_drafts)

        # Step 4: 反向回填 evidence.entities
        backfill_evidence_entities(evidences, entities)

        return {
            "evidences": evidences,
            "entities": entities,
            "relations": relations,
        }

    def _build_evidence_draft(
        self,
        source_text: str,
        section: Any,
        page: Any,
    ) -> dict[str, Any]:
        """从 source_text 构建 Evidence 草稿。

        Evidence 类型由 source_text 内容推断（简化版：默认 Imaging Finding）。
        完整的 evidence_type 分类留待后续优化或 LLM 辅助推断。
        """
        return {
            "source_text": source_text,
            "section": section,
            "page": page,
            "evidence_type": "Imaging Finding",  # 默认类型，后续可优化
            "assertion_type": "Positive",  # 默认，由 relation 的 assertion_type 覆盖
            "evidence_statement": source_text[:200],  # 简化：截取前 200 字符作为 statement
        }

    def _fuzzy_match_mention(
        self,
        mention: str,
        entity_type: str,
        mapping: dict[tuple[str, str], str],
    ) -> str | None:
        """模糊匹配 mention（包含关系或子串匹配）。

        用于 LLM 在 relation 中对 mention 做了轻微改写的情况。
        """
        mention_lower = mention.lower()
        for (key_mention, key_type), ent_id in mapping.items():
            if key_type != entity_type:
                continue
            # 子串匹配（双向）
            if mention_lower in key_mention.lower() or key_mention.lower() in mention_lower:
                return ent_id
        return None


# --------------------------------------------------------------------------- #
# 内部校验异常
# --------------------------------------------------------------------------- #
class _ValidationError(Exception):
    """轻量校验失败，携带 ErrorCode + feedback 供重试。"""

    def __init__(self, error_code: ErrorCode, feedback: str) -> None:
        super().__init__(feedback)
        self.error_code = error_code
        self.feedback = feedback


# --------------------------------------------------------------------------- #
# P7 校验
# --------------------------------------------------------------------------- #
def validate_result(
    document_id: str,
    result: dict[str, list[dict[str, Any]]],
) -> list[ValidationIssue]:
    """对统一抽取结果执行 P7 校验（JSON Schema + Rule-based）。

    与 SingleDocRunner._validate_all 使用同一套规则与校验器：
        1. 逐条 JSON Schema：结构 / 必填 / 类型 / 枚举 / additionalProperties
        2. Rule-based：Domain/Range、引用完整性、document_id 一致性、禁用关系

    参数：
        document_id  文献 ID
        result       extract() 返回的 {evidences, entities, relations}

    返回：
        ValidationIssue 列表（空 = 全部通过）。
        本函数只报告问题，不删除任何数据 —— 入库或送人工审核由调用方决定。
    """
    evidences = result.get("evidences", [])
    entities = result.get("entities", [])
    relations = result.get("relations", [])

    issues: list[ValidationIssue] = []
    for ev in evidences:
        issues += _JSON_VALIDATOR.validate(ev, "evidence")
    for ent in entities:
        issues += _JSON_VALIDATOR.validate(ent, "entity")
    for rel in relations:
        issues += _JSON_VALIDATOR.validate(rel, "relation")
    issues += _RULE_VALIDATOR.validate(evidences, entities, relations, document_id)
    return issues


def summarize_issues(issues: list[ValidationIssue]) -> dict[str, Any]:
    """把 ValidationIssue 列表汇总为可落盘的统计结构。"""
    by_code = Counter(i.error_code.value for i in issues)
    blocking = [i for i in issues if i.error_code in _BLOCKING_ERRORS]
    return {
        "issue_count": len(issues),
        "blocking_count": len(blocking),
        "by_error_code": dict(sorted(by_code.items(), key=lambda kv: (-kv[1], kv[0]))),
        "blocking_issues": [
            {
                "error_code": i.error_code.value,
                "field": i.field,
                "ref_id": i.ref_id,
                "message": i.message,
            }
            for i in blocking
        ],
    }


# --------------------------------------------------------------------------- #
# 缓存保存
# --------------------------------------------------------------------------- #
def save_unified_cache(
    document_id: str,
    result: dict[str, list[dict[str, Any]]],
    model: str,
    project_root: Path,
    metadata: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> Path:
    """保存统一抽取结果到缓存文件。

    缓存路径：data/extracted/{RUN_VERSION}/{doc_id}_unified.json
    缓存格式：{document_id, model, run_version, extracted_at, metadata,
               evidence_count, entity_count, relation_count, canonical_count,
               validation, evidences, entities, relations}

    参数：
        document_id  文献 ID
        result       extract() 返回的 {evidences, entities, relations}
        model        LLM 模型名
        project_root 项目根路径
        metadata     文献元数据（可选）
        validation   summarize_issues() 的汇总结果（可选，缺省表示未做 P7）
    返回：
        缓存文件路径
    """
    cache_path = get_cache_path(document_id, "unified", project_root)
    ensure_dir(cache_path.parent)

    entities = result.get("entities", [])
    cache_data = {
        "document_id": document_id,
        "model": model,
        "run_version": get_run_version(),
        "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": metadata or {},
        "evidence_count": len(result.get("evidences", [])),
        "entity_count": len(entities),
        "relation_count": len(result.get("relations", [])),
        "canonical_count": sum(1 for e in entities if e.get("canonical_name")),
        "validation": validation,
        "evidences": result.get("evidences", []),
        "entities": entities,
        "relations": result.get("relations", []),
    }
    cache_path.write_text(
        json.dumps(cache_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cache_path


# --------------------------------------------------------------------------- #
# 命令行入口
# --------------------------------------------------------------------------- #
def run_validation_report(
    document_id: str,
    result: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """执行 P7 校验并打印完整报告（不截断），返回可落盘的汇总结构。"""
    print(f"\nP7 校验中 ...")
    issues = validate_result(document_id, result)
    summary = summarize_issues(issues)
    print(f"  issue 总数   : {summary['issue_count']}")
    print(f"  阻断性问题数 : {summary['blocking_count']}")
    if summary["by_error_code"]:
        print(f"\nP7 问题分类:")
        for code, cnt in summary["by_error_code"].items():
            print(f"  {code:28s}: {cnt}")
    else:
        print("  [OK] 全部通过，无 issue")

    blocking_issues = summary["blocking_issues"]
    if blocking_issues:
        print(f"\n阻断性问题明细（共 {len(blocking_issues)} 条）:")
        for i, b in enumerate(blocking_issues, 1):
            print(
                f"  [{i}] {b['error_code']:26s} ref={b['ref_id']} "
                f"field={b['field']} | {b['message']}"
            )
    return summary


def _main() -> int:
    """命令行入口：单篇统一抽取（一步生成 Entity + Relation + Evidence）。

    用法：
        python -m pipeline.unified_extractor BT000008          # 读取或抽取
        python -m pipeline.unified_extractor BT000008 --force  # 强制重新抽取
        python -m pipeline.unified_extractor BT000008 --validate  # 只重跑 P7（不调用 LLM）
        python -m pipeline.unified_extractor BT000008 --from-file data/agent_gold/BT000001_raw.json
            # 不调用 LLM：把外部标注者（人 / Agent）产出的 raw JSON 走同一条
            #   后处理 + P7 + 落盘链路，配合独立 RUN_VERSION 与 API 结果做 A/B

    前置条件：
        - .env 配置了 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
        - metadata/first/file_index.csv 存在
        - 对应 Markdown 文件存在
    """
    if len(sys.argv) < 2:
        print("用法: python -m pipeline.unified_extractor <document_id> [--force] [--validate]")
        return 2

    doc_id = sys.argv[1]
    force = "--force" in sys.argv
    validate_only = "--validate" in sys.argv
    project_root = Path(__file__).resolve().parent.parent

    # --from-file：跳过 LLM，把外部标注者（人 / Agent）产出的 raw JSON
    # 走与 API 结果完全相同的后处理 + P7 链路，保证两套结果可直接对比。
    from_file: str | None = None
    annotator = "Qoder-Agent"
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--from-file" and i + 1 < len(argv):
            from_file = argv[i + 1]
        if arg == "--annotator" and i + 1 < len(argv):
            annotator = argv[i + 1]

    if from_file:
        raw_path = Path(from_file)
        if not raw_path.is_absolute():
            raw_path = project_root / raw_path
        if not raw_path.exists():
            print(f"标注文件不存在: {raw_path}")
            return 1
        print(f"version   : {get_run_version()}")
        print(f"标注来源  : {annotator}（{raw_path.name}，不调用 LLM）")

        # ---- Layer 1: 原始字节备份 ----
        raw_bytes = raw_path.read_bytes()
        backup_dir = project_root / "data" / "agent_generated" / "raw_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{doc_id}_raw.json"
        backup_path.write_bytes(raw_bytes)
        print(f"原始字节备份: {backup_path}")

        # ---- JSON 解析 ----
        try:
            raw_obj = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"[ERROR] JSON 解析失败: {exc}")
            print("停止后处理，不将空列表当成成功解析。")
            return 1

        # ---- document_id 一致性校验（独立执行，不因 ID 不一致而忽略其他诊断）----
        json_doc_id = raw_obj.get("document_id", "")
        if json_doc_id and json_doc_id != doc_id:
            print(f"[ERROR] document_id 不一致: CLI={doc_id} vs JSON={json_doc_id}")
            print("继续执行其他诊断，但此条记录为阻断性错误。")

        # ---- _parse_and_validate ----
        extractor = UnifiedExtractorImpl(llm_client=None, normalizer=EntityNormalizerImpl(project_root))  # pyright: ignore[reportArgumentType]
        raw_text = raw_bytes.decode("utf-8")
        try:
            entities_raw, relations_raw = extractor._parse_and_validate(raw_text)
        except _ValidationError as exc:
            print(f"标注结果不合格（{exc.error_code}）:\n{exc.feedback}")
            return 1

        # 深拷贝 raw 数据，防止 _post_process 就地修改污染 Layer 2 边界
        raw_entities_snapshot = copy.deepcopy(entities_raw)
        raw_relations_snapshot = copy.deepcopy(relations_raw)

        # ---- _post_process ----
        processed = extractor._post_process(doc_id, entities_raw, relations_raw)
        print(
            f"\n后处理完成: Evidence {len(processed['evidences'])} | "
            f"Entity {len(processed['entities'])} | Relation {len(processed['relations'])}"
        )

        from pipeline.metadata_provider import MetadataProviderImpl

        try:
            metadata = MetadataProviderImpl(project_root).get_metadata(doc_id)
        except Exception as exc:
            print(f"元数据读取失败: {exc}")
            metadata = {}

        # ---- 构造 ExtractionResult（三层边界）----
        result = ExtractionResult(
            document_id=doc_id,
            raw_response=raw_text,
            raw_entities=raw_entities_snapshot,
            raw_relations=raw_relations_snapshot,
            processed=processed,
            metadata=metadata,
        )

        # ---- 定位 Markdown（用于阶段一原始质检）----
        markdown_path: Path | None = None
        try:
            from pipeline.markdown_reader import MarkdownReaderImpl
            reader = MarkdownReaderImpl(project_root)
            _, md_path = reader.read(doc_id)
            markdown_path = md_path
        except FileNotFoundError:
            print(f"[WARN] Markdown 不存在，阶段一原始质检将被跳过（标记为 incomplete）")
        except Exception as exc:
            print(f"[WARN] Markdown 定位失败: {exc}，阶段一原始质检将被跳过")

        # ---- 两阶段校验 ----
        print(f"\n两阶段校验中 ...")
        vr = run_full_validation(doc_id, result, markdown_path)
        print(f"  阶段一状态: {vr.stage1_status}")
        if vr.validation_incomplete:
            print(f"  [WARN] 校验不完整: 阶段一被跳过，不能视为完全通过")
        print(f"  阶段一 issues: {len(vr.stage1_issues)}")
        print(f"  阶段二 issues: {len(vr.stage2_issues)}")
        print(f"  合计: ERROR={vr.error_count} WARN={vr.warn_count} REVIEW={vr.review_count}")
        print(f"  has_blocking: {vr.has_blocking}")

        # ---- 保存校验报告 ----
        report_dir = project_root / "data" / "agent_generated" / "validation_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{doc_id}_validation_report.json"
        report_data = {
            "document_id": doc_id,
            "stage1_status": vr.stage1_status,
            "validation_incomplete": vr.validation_incomplete,
            "error_count": vr.error_count,
            "warn_count": vr.warn_count,
            "review_count": vr.review_count,
            "has_blocking": vr.has_blocking,
            "stage1_issues": [
                {"error_code": i.error_code.value, "severity": i.severity,
                 "field": i.field, "ref_id": i.ref_id, "message": i.message}
                for i in vr.stage1_issues
            ],
            "stage2_issues": [
                {"error_code": i.error_code.value, "severity": i.severity,
                 "field": i.field, "ref_id": i.ref_id, "message": i.message}
                for i in vr.stage2_issues
            ],
            "fingerprints": sorted([str(f) for f in vr.fingerprint_set()]),
        }
        report_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"校验报告: {report_path}")

        # ---- 保存缓存 ----
        summary = summarize_issues(vr.all_issues)
        cache_path = save_unified_cache(
            doc_id, result.processed, annotator, project_root, metadata, summary
        )
        print(f"\n已保存缓存: {cache_path}")
        return 0

    # 构造 LLM 客户端
    try:
        client = LLMClient.from_env()
    except ValueError as exc:
        print(f"配置错误: {exc}")
        return 2

    run_version = get_run_version()
    print(f"endpoint : {client._endpoint}")
    print(f"model    : {client.model}")
    print(f"version  : {run_version}")
    print(f"方案     : C（一步抽取 + Python 包装 Evidence）")

    # 缓存路径
    cache_path = get_cache_path(doc_id, "unified", project_root)

    # 只重跑 P7：读缓存 → 校验 → 打印报告（不调用 LLM，不消耗 API 额度）
    if validate_only:
        if not cache_path.exists():
            print(f"缓存不存在，无法只重跑校验: {cache_path}")
            return 1
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        result = {
            "evidences": cache.get("evidences", []),
            "entities": cache.get("entities", []),
            "relations": cache.get("relations", []),
        }
        print(f"document_id: {doc_id}")
        print(f"读取缓存: {cache_path}")
        print(f"  Evidence {len(result['evidences'])} | "
              f"Entity {len(result['entities'])} | "
              f"Relation {len(result['relations'])}")

        write_back = "--write" in sys.argv
        if not write_back:
            # 默认只读：旧缓存产出时既没做词典标准化，Relation 也携带了契约禁止的
            # source_text/page/section 字段。修复这两项需要改写缓存文件，
            # 因此仅在显式 --write 时执行。
            print("\n（只读模式：未做词典标准化修复。加 --write 可修复并写回缓存）")
            summary = run_validation_report(doc_id, result)
            return 0

        # --write：补词典标准化 + 剔除 Relation 违规字段，然后写回缓存
        normalizer = EntityNormalizerImpl(project_root)
        result["entities"] = [
            normalizer.normalize(e, doc_id) for e in result["entities"]
        ]
        stripped = 0
        for rel in result["relations"]:
            removed = [k for k in ("source_text", "page", "section") if k in rel]
            for k in removed:
                rel.pop(k)
            stripped += 1 if removed else 0
        print(f"  已剔除 {stripped} 条 Relation 的违规字段（溯源改由 evidence_ids 承担）")
        print(f"  词典已标准化实体: "
              f"{sum(1 for e in result['entities'] if e.get('canonical_name'))}")
        summary = run_validation_report(doc_id, result)
        save_unified_cache(
            doc_id,
            result,
            cache.get("model", ""),
            project_root,
            cache.get("metadata", {}),
            summary,
        )
        print(f"\n已把 P7 结果写回缓存: {cache_path}")
        return 0

    # 检查缓存
    if cache_path.exists() and not force:
        print(f"\n读取缓存: {cache_path}")
        print(f"（如需重新抽取，加 --force 参数）\n")
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        metadata = cache.get("metadata", {})
        print(f"标题      : {metadata.get('title', '')[:60]}")
        print(f"期刊      : {metadata.get('journal', '')} ({metadata.get('year', '')})")
        print(f"抽取时间  : {cache.get('extracted_at', '?')}")
        print(f"模型      : {cache.get('model', '?')}")
        print(f"Evidence : {cache.get('evidence_count', 0)}")
        print(f"Entity   : {cache.get('entity_count', 0)}")
        print(f"Relation : {cache.get('relation_count', 0)}")
        print(f"词典已标准化实体: {cache.get('canonical_count', 0)}")
        validation = cache.get("validation")
        if validation:
            print(f"P7       : issue {validation.get('issue_count', 0)} "
                  f"/ 阻断 {validation.get('blocking_count', 0)}")
        else:
            print(f"P7       : 未校验（可用 --validate 补跑，不调用 LLM）")
        return 0

    # 需要抽取
    print(f"\n开始一步抽取 document_id={doc_id}...\n")

    from pipeline.markdown_reader import MarkdownReaderImpl
    from pipeline.metadata_provider import MetadataProviderImpl

    reader = MarkdownReaderImpl(project_root)
    provider = MetadataProviderImpl(project_root)
    extractor = UnifiedExtractorImpl(client)

    # 1. 读取 Markdown
    try:
        md_text, md_path = reader.read(doc_id)
    except FileNotFoundError as exc:
        print(f"读取失败: {exc}")
        return 1
    print(f"Markdown  : {md_path.name}（{len(md_text)} 字符）")

    # 2. 读取元数据
    try:
        metadata = provider.get_metadata(doc_id)
    except Exception as exc:
        print(f"元数据读取失败: {exc}")
        metadata = {}
    print(f"标题      : {metadata.get('title', '')[:60]}")
    print(f"期刊      : {metadata.get('journal', '')} ({metadata.get('year', '')})")

    # 3. 调用统一抽取
    print(f"\n正在调用 LLM 一步抽取 Entity + Relation（可能需要 60-600 秒）...")
    try:
        result = extractor.extract(doc_id, md_text, metadata)
    except ExtractionError as exc:
        print(f"抽取失败: {exc}")
        return 1

    evidences = result.processed["evidences"]
    entities = result.processed["entities"]
    relations = result.processed["relations"]

    print(f"\n抽取完成:")
    print(f"  Evidence : {len(evidences)}")
    print(f"  Entity   : {len(entities)}")
    print(f"  Relation : {len(relations)}")
    print(f"  词典已标准化实体: {sum(1 for e in entities if e.get('canonical_name'))}")

    # 4. P7 校验（JSON Schema + Rule-based）
    summary = run_validation_report(doc_id, result.processed)

    # 5. 保存缓存（含 P7 汇总）
    cache_path = save_unified_cache(
        doc_id, result.processed, client.model, project_root, metadata, summary
    )
    print(f"\n已保存缓存: {cache_path}")

    # 6. 统计
    ent_types = Counter(e.get("entity_type", "?") for e in entities)
    rel_types = Counter(r.get("relation_type", "?") for r in relations)
    assert_types = Counter(r.get("assertion_type", "?") for r in relations)

    print(f"\nEntity 类型统计:")
    for t, c in ent_types.most_common():
        print(f"  {t:20s}: {c}")

    print(f"\nRelation 类型统计:")
    for t, c in rel_types.most_common():
        print(f"  {t:20s}: {c}")

    print(f"\nAssertion 类型统计:")
    for t, c in assert_types.most_common():
        print(f"  {t:20s}: {c}")

    # 7. 显示前几条
    print(f"\n前 {min(5, len(relations))} 条 Relation:")
    for i, rel in enumerate(relations[:5]):
        rtype = rel.get("relation_type", "?")
        head = rel.get("head_entity_id", "?")[:25]
        tail = rel.get("tail_entity_id", "?")[:25]
        atype = rel.get("assertion_type", "?")
        print(f"  [{i+1}] {head} -- {rtype} --> {tail} | {atype}")

    # 7. 与旧方案对比（如果有旧缓存）
    old_ev_path = get_cache_path(doc_id, "evidence", project_root)
    old_ent_path = get_cache_path(doc_id, "entity", project_root)
    old_rel_path = get_cache_path(doc_id, "relation", project_root)
    if old_rel_path.exists():
        old_rel = json.loads(old_rel_path.read_text(encoding="utf-8"))["relations"]
        old_ev = json.loads(old_ev_path.read_text(encoding="utf-8"))["evidences"]
        old_ent = json.loads(old_ent_path.read_text(encoding="utf-8"))["entities"]
        print(f"\n--- 与旧方案（三阶段）对比 ---")
        print(f"  {'指标':<12} {'旧方案':>8} {'新方案':>8} {'变化':>8}")
        print(f"  {'Evidence':<12} {len(old_ev):>8} {len(evidences):>8} {len(evidences)-len(old_ev):>+8}")
        print(f"  {'Entity':<12} {len(old_ent):>8} {len(entities):>8} {len(entities)-len(old_ent):>+8}")
        print(f"  {'Relation':<12} {len(old_rel):>8} {len(relations):>8} {len(relations)-len(old_rel):>+8}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
