"""单文档完整流水线编排（架构设计 D-2 / D-3 / D-5 / D-6）。

流水线阶段（与 state_manager.STAGE_ORDER 对齐）：

    1. METADATA    读取 document_metadata.csv 行 + MinerU Markdown 原文
    2. EVIDENCE    D-2 阶段 A：LLM 抽 Evidence（entities=[]）→ 分配 evidence_id
    3. ENTITY      D-2 阶段 B：LLM 抽 Entity（填 evidence_ids）→ 分配 entity_id + 词典标准化
    4. BACKFILL    D-2 阶段 C：Python 据 entity.evidence_ids 反向回填 Evidence.entities（D-6 允许空）
    5. RELATION    LLM 抽 Relation（head/tail/evidence_ids 引用已分配 ID）→ 分配 relation_id
    6. VALIDATION  JSON Schema 校验 + Rule-based 校验（Domain/Range、溯源、双向一致、D-5 拦截）
    7. PERSIST     落盘 final CSV（D-3：JSON 运行时 / CSV 持久化 + entity_evidence 桥接表）

责任分配（Schema_rules）：
    LLM    ：发现实体、抽 Evidence/Relation 语义
    Python ：ID 生成、落盘、反向回填、校验编排、词典标准化触发
    本模块 ：编排上述步骤 + 检查点推进 + 错误码→状态机映射

本文件只提供编排框架与接口契约（Protocol）；extractors / validators / stores 的
具体实现见 P4-P7。各 Protocol 方法签名即后续实现的硬约束。

命令示例（自检，使用本文件内置 stub）：
    python -m pipeline.single_doc_runner CV001886
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pipeline.id_generator import (
    make_entity_id,
    make_evidence_id,
    make_relation_id,
)
from pipeline.state_manager import (
    Checkpoint,
    DocState,
    ErrorCode,
    Stage,
    StateManager,
)


# schemas/ 目录（供 P7 JSONSchemaValidator 实现加载 *.schema.json）
SCHEMAS_DIR: Path = Path(__file__).resolve().parent.parent / "schemas"


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class ValidationIssue:
    """单条校验问题。"""

    error_code: ErrorCode
    message: str
    field: str = ""
    ref_id: str = ""
    severity: str = "ERROR"  # "ERROR"（阻断）/ "WARN"（复核队列）/ "REVIEW"（人工判断）

    def __str__(self) -> str:  # 便于日志打印
        return f"[{self.severity}][{self.error_code.value}] {self.field}: {self.message} (ref={self.ref_id})"

    def fingerprint(self) -> tuple:
        """稳定指纹，用于 --apply 前后比较（不依赖 message 文字）。"""
        return (self.error_code, self.field, self.ref_id)


@dataclass
class RunResult:
    """单文档运行结果。"""

    document_id: str
    state: DocState
    stage: Stage | None
    retry_count: int
    evidence_count: int
    entity_count: int
    relation_count: int
    issues: list[ValidationIssue] = field(default_factory=list)
    checkpoint_path: str = ""
    final_paths: dict[str, str] = field(default_factory=dict)


class ExtractionError(Exception):
    """抽取阶段可恢复错误，携带 ErrorCode 供状态机分类重试。"""

    def __init__(self, error_code: ErrorCode, message: str) -> None:
        super().__init__(f"[{error_code.value}] {message}")
        self.error_code = error_code
        self.message = message


# --------------------------------------------------------------------------- #
# 接口契约（Protocol）—— P4-P7 实现须满足
# --------------------------------------------------------------------------- #
@runtime_checkable
class MetadataProvider(Protocol):
    """P-storage：按 document_id 返回 document_metadata.csv 元数据行。"""

    def get_metadata(self, document_id: str) -> dict[str, Any]:
        """返回该文献元数据 dict（含 title/journal/year/document_type 等）。"""
        ...


@runtime_checkable
class MarkdownReader(Protocol):
    """P-storage：读取 MinerU OCR Markdown 原文。"""

    def read(self, document_id: str) -> tuple[str, Path]:
        """返回 (markdown 文本, 源 .md 文件路径)。"""
        ...


@runtime_checkable
class EvidenceExtractor(Protocol):
    """P4：D-2 阶段 A，LLM 抽 Evidence（entities 留空）。"""

    def extract(
        self,
        document_id: str,
        markdown: str,
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """返回 Evidence 草稿列表；每条不含 evidence_id、entities 置 []。"""
        ...


@runtime_checkable
class EntityExtractor(Protocol):
    """P5：D-2 阶段 B，LLM 抽 Entity 并填 evidence_ids。"""

    def extract(
        self,
        document_id: str,
        markdown: str,
        evidences: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """返回 Entity 草稿列表；每条不含 entity_id，含 evidence_ids。"""
        ...


@runtime_checkable
class RelationExtractor(Protocol):
    """P6：LLM 抽 Relation，head/tail/evidence_ids 引用已分配 ID。"""

    def extract(
        self,
        document_id: str,
        markdown: str,
        entities: list[dict[str, Any]],
        evidences: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """返回 Relation 草稿列表；每条不含 relation_id，含 head/tail/evidence_ids。"""
        ...


@runtime_checkable
class EntityNormalizer(Protocol):
    """P5：词典标准化，填 canonical_name / ontology_id（mention 保持原文）。"""

    def normalize(self, entity: dict[str, Any], document_id: str) -> dict[str, Any]:
        """返回补全 canonical_name / ontology_id 的 entity（无法映射则置 null）。"""
        ...


@runtime_checkable
class JSONSchemaValidator(Protocol):
    """P7：基于 schemas/*.schema.json 的结构校验（jsonschema 库）。"""

    def validate(self, instance: dict[str, Any], schema_name: str) -> list[ValidationIssue]:
        """schema_name ∈ {'evidence','entity','relation'}；返回 issue 列表（空=通过）。"""
        ...


@runtime_checkable
class RuleValidator(Protocol):
    """P7：业务规则校验（Domain/Range、溯源、双向一致、D-5 RECOMMENDED_BY 拦截）。"""

    def validate(
        self,
        evidences: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        document_id: str,
    ) -> list[ValidationIssue]:
        ...


@runtime_checkable
class PersistenceStore(Protocol):
    """P-storage：D-3 落盘 final CSV（含 entity_evidence 桥接表）。"""

    def persist(
        self,
        document_id: str,
        evidences: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Path]:
        """返回各输出文件路径（evidence_metadata.csv / entity_metadata.csv /
        relation_evidence.csv / entity_evidence.csv 等）。"""
        ...


# --------------------------------------------------------------------------- #
# ID 分配 + 去重合并（D-1 / §15.1 / §15.2）
# --------------------------------------------------------------------------- #
def assign_evidence_ids(
    document_id: str,
    drafts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """为 Evidence 草稿分配 evidence_id，初始化 entities=[]（D-2 阶段 A）。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in drafts:
        src = d.get("source_text", "")
        if not src or not str(src).strip():
            raise ExtractionError(
                ErrorCode.MISSING_REQUIRED_FIELD,
                "Evidence 缺少 source_text（Evidence_schema §7）",
            )
        eid = make_evidence_id(document_id, str(src))
        if eid in seen:
            continue  # 同文献同原文 → 合并（§15.1 证据级去重）
        seen.add(eid)
        item = dict(d)
        item["evidence_id"] = eid
        item["document_id"] = document_id
        item.setdefault("entities", [])  # D-6：中间态允许空
        out.append(item)
    return out


def assign_entity_ids(
    document_id: str,
    drafts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """为 Entity 草稿分配 entity_id；同 mention+type 自动合并 evidence_ids（§15.1）。"""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for d in drafts:
        mention = d.get("mention", "")
        etype = d.get("entity_type", "")
        if not mention or not etype:
            raise ExtractionError(
                ErrorCode.MISSING_REQUIRED_FIELD,
                "Entity 缺少 mention 或 entity_type（Entity_schema §3/§4）",
            )
        eid = make_entity_id(document_id, str(mention), str(etype))
        ev_ids = list(d.get("evidence_ids", []))
        if eid in merged:
            target = merged[eid]
            for ev_id in ev_ids:
                if ev_id not in target["evidence_ids"]:
                    target["evidence_ids"].append(ev_id)
        else:
            item = dict(d)
            item["entity_id"] = eid
            item["document_id"] = document_id
            item.setdefault("canonical_name", None)
            item.setdefault("ontology_id", None)
            item["evidence_ids"] = ev_ids
            merged[eid] = item
            order.append(eid)
    return [merged[eid] for eid in order]


def assign_relation_ids(
    document_id: str,
    drafts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """为 Relation 草稿分配 relation_id；同三元组合并 evidence_ids（§15.2）。"""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for d in drafts:
        head = d.get("head_entity_id", "")
        tail = d.get("tail_entity_id", "")
        rtype = d.get("relation_type", "")
        atype = d.get("assertion_type", "")
        if not head or not tail or not rtype:
            raise ExtractionError(
                ErrorCode.MISSING_REQUIRED_FIELD,
                "Relation 缺少 head_entity_id/tail_entity_id/relation_type",
            )
        # assertion_type 参与去重：同三元组的 Positive/Negative 是两条不同断言，不得合并
        rid = make_relation_id(document_id, str(head), str(rtype), str(tail), str(atype))
        ev_ids = list(d.get("evidence_ids", []))
        if rid in merged:
            target = merged[rid]
            for ev_id in ev_ids:
                if ev_id not in target["evidence_ids"]:
                    target["evidence_ids"].append(ev_id)
        else:
            item = dict(d)
            item["relation_id"] = rid
            item["document_id"] = document_id
            item["evidence_ids"] = ev_ids
            merged[rid] = item
            order.append(rid)
    return [merged[rid] for rid in order]


def backfill_evidence_entities(
    evidences: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> list[ValidationIssue]:
    """D-2 阶段 C：据 entity.evidence_ids 反向回填 evidence.entities。

    entity.evidence_ids 引用不存在的 evidence → 记录 EVIDENCE_NOT_FOUND。
    Evidence.entities 允许保持空数组（D-6 中间态）。
    """
    ev_map = {e["evidence_id"]: e for e in evidences}
    issues: list[ValidationIssue] = []
    for ent in entities:
        ent_id = ent["entity_id"]
        for eid in ent.get("evidence_ids", []):
            ev = ev_map.get(eid)
            if ev is None:
                issues.append(
                    ValidationIssue(
                        ErrorCode.EVIDENCE_NOT_FOUND,
                        f"实体引用了不存在的 evidence_id {eid}",
                        "evidence_ids",
                        ent_id,
                    )
                )
                continue
            if ent_id not in ev["entities"]:
                ev["entities"].append(ent_id)
    return issues


# --------------------------------------------------------------------------- #
# 编排器
# --------------------------------------------------------------------------- #
class SingleDocRunner:
    """单文档完整流水线编排器。

    依赖通过构造函数注入；P4-P7 提供具体实现。本类只负责编排、ID 分配、回填、
    去重、检查点推进与错误码→状态机映射。
    """

    def __init__(
        self,
        state_manager: StateManager,
        metadata_provider: MetadataProvider,
        markdown_reader: MarkdownReader,
        evidence_extractor: EvidenceExtractor,
        entity_extractor: EntityExtractor,
        relation_extractor: RelationExtractor,
        normalizer: EntityNormalizer,
        json_validator: JSONSchemaValidator,
        rule_validator: RuleValidator,
        persistence_store: PersistenceStore,
    ) -> None:
        self.sm = state_manager
        self.metadata_provider = metadata_provider
        self.markdown_reader = markdown_reader
        self.evidence_extractor = evidence_extractor
        self.entity_extractor = entity_extractor
        self.relation_extractor = relation_extractor
        self.normalizer = normalizer
        self.json_validator = json_validator
        self.rule_validator = rule_validator
        self.persistence_store = persistence_store

    def run(self, document_id: str) -> RunResult:
        """运行单文档完整流水线。

        正常完成返回 SUCCESS 的 RunResult；
        遇可重试 ExtractionError → 标记 RETRY 并重新抛出，交由 batch_runner 重试；
        遇不可重试错误 → 标记 MANUAL_REVIEW 并返回带 issues 的 RunResult。
        """
        cp = self.sm.start(document_id)
        evidences: list[dict[str, Any]] = []
        entities: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        issues: list[ValidationIssue] = []

        try:
            # 1. METADATA
            metadata = self.metadata_provider.get_metadata(document_id)
            markdown, _src = self.markdown_reader.read(document_id)
            self.sm.complete_stage(cp, Stage.METADATA)

            # 2. EVIDENCE（阶段 A，entities=[]）
            ev_drafts = self.evidence_extractor.extract(document_id, markdown, metadata)
            evidences = assign_evidence_ids(document_id, ev_drafts)
            self._write_artifact(cp, Stage.EVIDENCE, evidences)
            self.sm.complete_stage(cp, Stage.EVIDENCE)

            # 3. ENTITY（阶段 B，填 evidence_ids）
            ent_drafts = self.entity_extractor.extract(document_id, markdown, evidences)
            entities = assign_entity_ids(document_id, ent_drafts)
            entities = [self.normalizer.normalize(e, document_id) for e in entities]
            self._write_artifact(cp, Stage.ENTITY, entities)
            self.sm.complete_stage(cp, Stage.ENTITY)

            # 4. BACKFILL（阶段 C，Python 反向回填）
            issues += backfill_evidence_entities(evidences, entities)
            self._write_artifact(cp, Stage.BACKFILL, evidences)
            self.sm.complete_stage(cp, Stage.BACKFILL)

            # 5. RELATION
            rel_drafts = self.relation_extractor.extract(
                document_id, markdown, entities, evidences
            )
            relations = assign_relation_ids(document_id, rel_drafts)
            self._write_artifact(cp, Stage.RELATION, relations)
            self.sm.complete_stage(cp, Stage.RELATION)

            # 6. VALIDATION
            issues += self._validate_all(evidences, entities, relations, document_id)
            self.sm.complete_stage(cp, Stage.VALIDATION)
            # 严重校验问题 → MANUAL_REVIEW（不进入 PERSIST）
            blocking = [i for i in issues if i.error_code in _BLOCKING_ERRORS]
            if blocking:
                self.sm.mark_failed(
                    cp,
                    blocking[0].error_code,
                    f"校验发现 {len(blocking)} 个阻断性问题",
                )
                return self._result(cp, evidences, entities, relations, issues)

            # 7. PERSIST
            final_paths = self.persistence_store.persist(
                document_id, evidences, entities, relations
            )
            self.sm.complete_stage(cp, Stage.PERSIST)
            self.sm.mark_success(cp)
            return self._result(
                cp, evidences, entities, relations, issues, final_paths
            )

        except ExtractionError as exc:
            self.sm.mark_failed(cp, exc.error_code, exc.message)
            if self.sm.can_retry(cp):
                # 交由 batch_runner 决定何时重跑（从 next_stage 恢复）
                raise
            return self._result(cp, evidences, entities, relations, issues)

    # -- 内部辅助 -------------------------------------------------------------
    def _write_artifact(
        self,
        cp: Checkpoint,
        stage: Stage,
        payload: list[dict[str, Any]],
    ) -> None:
        """将阶段产物 JSON 落盘到 intermediate/{doc_id}.v{N}/（运行时态，D-3）。"""
        path = self.sm.artifact_path(cp, stage, "json")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        # 记录到 checkpoint.artifacts
        cp.artifacts[stage.value] = str(path)

    def _validate_all(
        self,
        evidences: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        document_id: str,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for ev in evidences:
            issues += self.json_validator.validate(ev, "evidence")
        for ent in entities:
            issues += self.json_validator.validate(ent, "entity")
        for rel in relations:
            issues += self.json_validator.validate(rel, "relation")
        issues += self.rule_validator.validate(evidences, entities, relations, document_id)
        return issues

    def _result(
        self,
        cp: Checkpoint,
        evidences: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        issues: list[ValidationIssue],
        final_paths: dict[str, Path] | None = None,
    ) -> RunResult:
        return RunResult(
            document_id=cp.document_id,
            state=cp.state,
            stage=cp.stage,
            retry_count=cp.retry_count,
            evidence_count=len(evidences),
            entity_count=len(entities),
            relation_count=len(relations),
            issues=issues,
            checkpoint_path=str(
                self.sm._checkpoint_path(  # noqa: SLF001  仅用于结果展示
                    self.sm._version_dir(cp.document_id, cp.version)  # noqa: SLF001
                )
            ),
            final_paths={k: str(v) for k, v in (final_paths or {}).items()},
        )


# 阻断性错误：命中即不落盘，直接 MANUAL_REVIEW
_BLOCKING_ERRORS = frozenset(
    {
        ErrorCode.SCHEMA_VALIDATION_FAILED,
        ErrorCode.MISSING_REQUIRED_FIELD,
        ErrorCode.INVALID_ENUM,
        ErrorCode.DOCUMENT_ID_MISMATCH,
        ErrorCode.DOMAIN_RANGE_MISMATCH,
        ErrorCode.SELF_LOOP_NOT_ALLOWED,
        ErrorCode.ENTITY_NOT_FOUND,
        ErrorCode.EVIDENCE_NOT_FOUND,
        ErrorCode.UNSUPPORTED_RELATION,  # D-5 RECOMMENDED_BY 在 V1 被拦截
        ErrorCode.SOURCE_TEXT_MISSING,
        ErrorCode.DUPLICATE_ENTITY,
        ErrorCode.DUPLICATE_RELATION,
        ErrorCode.DUPLICATE_EVIDENCE,
    }
)


def severity_for(error_code: ErrorCode) -> str:
    """根据 ErrorCode 返回严重级别（统一阶段一和阶段二的阻断判定）。"""
    return "ERROR" if error_code in _BLOCKING_ERRORS else "WARN"


# --------------------------------------------------------------------------- #
# 自检：内置 stub 实现（仅用于验证编排/ID/状态/回填/去重链路，非 P4-P7 真实实现）
# --------------------------------------------------------------------------- #
class _StubMetadata:
    """Stub：返回固定元数据。"""

    def get_metadata(self, document_id: str) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "title": "Stub: acute ischemic stroke DWI findings",
            "journal": "Stroke.",
            "year": 2021,
            "document_type": "Journal Article",
            "study_type": "Retrospective Cohort",
            "population": "Patients",
            "language": "en",
        }


class _StubMarkdown:
    """Stub：返回固定 Markdown 文本。"""

    def read(self, document_id: str) -> tuple[str, Path]:
        text = (
            "# Acute ischemic stroke on DWI\n\n"
            "Restricted diffusion was observed on DWI in patients with acute ischemic stroke. "
            "DWI showed higher sensitivity than conventional MRI."
        )
        return text, Path(f"<stub>/{document_id}.md")


class _StubEvidenceExtractor:
    """Stub：返回 2 条 Evidence 草稿（无 evidence_id、entities=[]）。"""

    def extract(self, document_id, markdown, metadata):  # type: ignore[no-untyped-def]
        return [
            {
                "evidence_type": "Imaging Finding",
                "evidence_statement": "Restricted diffusion observed on DWI in AIS patients.",
                "source_text": "Restricted diffusion was observed on DWI in patients with acute ischemic stroke.",
                "section": "Results",
                "page": 3,
                "assertion_type": "Positive",
                "study_design": "Retrospective Cohort",
                "sample_size": {"total_n": 120, "groups": [{"name": "patients", "n": 80}]},
                "entities": [],
            },
            {
                "evidence_type": "Diagnostic Finding",
                "evidence_statement": "DWI showed higher sensitivity than conventional MRI.",
                "source_text": "DWI showed higher sensitivity than conventional MRI.",
                "section": "Results",
                "page": 4,
                "assertion_type": "Comparative",
                "study_design": "Retrospective Cohort",
                "sample_size": None,
                "entities": [],
            },
        ]


class _StubEntityExtractor:
    """Stub：返回 3 条 Entity 草稿（含 evidence_ids），其中两条 mention+type 相同以验证去重。"""

    def extract(self, document_id, markdown, evidences):  # type: ignore[no-untyped-def]
        ev0 = evidences[0]["evidence_id"]
        ev1 = evidences[1]["evidence_id"]
        return [
            {
                "entity_type": "Disease",
                "mention": "acute ischemic stroke",
                "source_text": "patients with acute ischemic stroke",
                "page": 3,
                "section": "Results",
                "evidence_ids": [ev0, ev1],
            },
            # 与上一条同 mention+type → 应触发 §15.1 合并
            {
                "entity_type": "Disease",
                "mention": "acute ischemic stroke",
                "source_text": "acute ischemic stroke (duplicate mention)",
                "page": 4,
                "section": "Discussion",
                "evidence_ids": [ev1],
            },
            {
                "entity_type": "MRISequence",
                "mention": "DWI",
                "source_text": "DWI showed higher sensitivity",
                "page": 4,
                "section": "Results",
                "evidence_ids": [ev1],
            },
            {
                "entity_type": "ImagingModality",
                "mention": "conventional MRI",
                "source_text": "conventional MRI",
                "page": 4,
                "section": "Results",
                "evidence_ids": [ev1],
            },
        ]


class _StubRelationExtractor:
    """Stub：返回 1 条 Relation 草稿（引用已分配 entity_id）。"""

    def extract(self, document_id, markdown, entities, evidences):  # type: ignore[no-untyped-def]
        by_mention = {e["mention"]: e["entity_id"] for e in entities}
        ev1 = evidences[1]["evidence_id"]
        return [
            {
                "head_entity_id": by_mention["DWI"],
                "relation_type": "COMPARED_WITH",
                "tail_entity_id": by_mention["conventional MRI"],
                "assertion_type": "Comparative",
                "evidence_ids": [ev1],
            },
            {
                "head_entity_id": by_mention["acute ischemic stroke"],
                "relation_type": "DIAGNOSED_BY",
                "tail_entity_id": by_mention["DWI"],
                "assertion_type": "Positive",
                "evidence_ids": [ev0] if False else [evidences[0]["evidence_id"]],
            },
        ]


class _StubNormalizer:
    """Stub：词典标准化占位（canonical_name 置 null，P5 接真实词典）。"""

    def normalize(self, entity, document_id):  # type: ignore[no-untyped-def]
        entity.setdefault("canonical_name", None)
        entity.setdefault("ontology_id", None)
        return entity


class _StubJSONValidator:
    """Stub：结构校验占位（P7 接 schemas/*.schema.json + jsonschema）。"""

    def validate(self, instance, schema_name):  # type: ignore[no-untyped-def]
        return []  # P3 自检默认通过


class _StubRuleValidator:
    """Stub：业务规则校验占位（P7 接 Domain/Range + D-5 拦截）。"""

    def validate(self, evidences, entities, relations, document_id):  # type: ignore[no-untyped-def]
        return []


class _StubPersistence:
    """Stub：落盘占位（P-storage 接真实 CSV + 桥接表）。"""

    def persist(self, document_id, evidences, entities, relations):  # type: ignore[no-untyped-def]
        return {
            "evidence": Path(f"<stub>/final/evidence_metadata.csv"),
            "entity": Path(f"<stub>/final/entity_metadata.csv"),
            "relation": Path(f"<stub>/final/relation_evidence.csv"),
            "entity_evidence": Path(f"<stub>/final/entity_evidence.csv"),
        }


def _build_stub_runner(data_dir: str) -> SingleDocRunner:
    """用内置 stub 装配一个可运行的 SingleDocRunner（仅自检用）。"""
    sm = StateManager(
        data_dir, schema_version="1.2", extractor_version="0.1.0", model="stub-self-test"
    )
    return SingleDocRunner(
        state_manager=sm,
        metadata_provider=_StubMetadata(),
        markdown_reader=_StubMarkdown(),
        evidence_extractor=_StubEvidenceExtractor(),
        entity_extractor=_StubEntityExtractor(),
        relation_extractor=_StubRelationExtractor(),
        normalizer=_StubNormalizer(),
        json_validator=_StubJSONValidator(),
        rule_validator=_StubRuleValidator(),
        persistence_store=_StubPersistence(),
    )


def _main() -> int:
    """命令行自检入口。

    用法：
        python -m pipeline.single_doc_runner <document_id> [data_dir]

    示例：
        python -m pipeline.single_doc_runner CV001886 ./data/_sdr_selftest
    """
    if len(sys.argv) < 2:
        print("用法: python -m pipeline.single_doc_runner <document_id> [data_dir]")
        return 2
    doc_id = sys.argv[1]
    data_dir = sys.argv[2] if len(sys.argv) > 2 else "./data/_sdr_selftest"
    runner = _build_stub_runner(data_dir)
    result = runner.run(doc_id)
    print("== SingleDocRunner 自检结果 ==")
    print(f"document_id   : {result.document_id}")
    print(f"state         : {result.state.value}")
    print(f"stage         : {result.stage.value if result.stage else None}")
    print(f"retry_count   : {result.retry_count}")
    print(f"evidence_count: {result.evidence_count}")
    print(f"entity_count  : {result.entity_count}")
    print(f"relation_count: {result.relation_count}")
    print(f"issues        : {len(result.issues)}")
    for i in result.issues:
        print(f"  - {i}")
    print(f"checkpoint    : {result.checkpoint_path}")
    print(f"final_paths   : {result.final_paths}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
