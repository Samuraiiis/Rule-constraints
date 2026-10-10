"""业务规则校验器（实现 single_doc_runner.RuleValidator 协议）。

基于 Schema_rules §10 / §14.2-§14.4 / D-5 / §15 做跨实体业务规则校验。
JSON Schema（结构校验）由 json_schema_validator 负责；本模块只做
Schema 无法表达的业务逻辑校验。

检查项：
    §10.1 / §14.2  Entity 存在性 — Relation.head/tail_entity_id 必须存在
    §10.2          document 一致性 — Relation.document_id == Head/Tail Entity.document_id
    §10.3 / §14.4  Evidence 存在性 — Relation.evidence_ids / Entity.evidence_ids 必须存在
    §10.4          Evidence 文献一致性 — Evidence.document_id == Relation/Entity.document_id
    §10.5          Domain/Range — Relation 的 Head/Tail entity_type 必须符合 §4 约束
    §10.6          Evidence 支持检查 — 无法溯源则 MANUAL_REVIEW_REQUIRED
    §14.2          Entity 唯一性 — entity_id 不重复（assign_entity_ids 已去重，这里二次确认）
    §14.3          Relation 唯一性 — relation_id 不重复（assign_relation_ids 已去重）
    §14.4          Evidence 唯一性 — evidence_id 不重复
    D-5            RECOMMENDED_BY 拦截 — V1 阶段不允许该 Relation
    §22            自环检查 — head_entity_id != tail_entity_id
    §14.2          Entity.source_text 存在
    §14.4          Evidence.source_text 存在

输入 / 输出：
    输入：evidences + entities + relations + document_id
    输出：list[ValidationIssue]（空=通过）

命令示例：
    # 自检
    python -m pipeline.rule_validator
"""
from __future__ import annotations

import sys
from typing import Any, Final

from pipeline.single_doc_runner import RuleValidator, ValidationIssue, severity_for
from pipeline.state_manager import ErrorCode

# --------------------------------------------------------------------------- #
# Domain/Range 约束（Relation_schema §4）
# key: relation_type, value: (head_entity_types, tail_entity_types)
# "Entity" 通配符表示任意 entity_type 均可（已展开为 None 表示不限制）
# --------------------------------------------------------------------------- #
_DOMAIN_RANGE: Final[dict[str, tuple[frozenset[str] | None, frozenset[str] | None]]] = {
    "HAS_FINDING": (frozenset({"Disease"}), frozenset({"ImagingFinding"})),
    "VISIBLE_ON": (frozenset({"ImagingFinding"}), frozenset({"MRISequence"})),
    "LOCATED_IN": (frozenset({"ImagingFinding", "Disease", "Pathology"}), frozenset({"Anatomy"})),
    "DIAGNOSED_BY": (
        frozenset({"Disease"}),
        frozenset({"ImagingModality", "MRISequence"}),
    ),
    "DIFFERENTIAL_DIAGNOSIS": (frozenset({"Disease"}), frozenset({"Disease"})),
    "HAS_SYMPTOM": (frozenset({"Disease"}), frozenset({"Symptom"})),
    "HAS_RISK_FACTOR": (frozenset({"Disease"}), frozenset({"RiskFactor"})),
    "HAS_COMPLICATION": (frozenset({"Disease"}), frozenset({"Complication"})),
    "TREATED_BY": (frozenset({"Disease"}), frozenset({"Treatment"})),
    # RECOMMENDED_BY: V1 被 D-5 拦截，不进入 Domain/Range 检查
    "RECOMMENDED_BY": (None, None),
    "PREDICTS": (None, None),  # Entity → Entity
    "ASSOCIATED_WITH": (None, None),  # Entity → Entity
    "ASSOCIATED_WITH_BIOMARKER": (frozenset({"Disease"}), frozenset({"Biomarker"})),
    "ASSOCIATED_WITH_MOLECULAR_FEATURE": (
        frozenset({"Disease"}),
        frozenset({"MolecularFeature"}),
    ),
    "ASSOCIATED_WITH_GENETIC_FEATURE": (
        frozenset({"Disease"}),
        frozenset({"GeneticFeature"}),
    ),
    "HAS_PATHOLOGY": (frozenset({"Disease"}), frozenset({"Pathology"})),
    "ASSESSED_BY": (None, None),  # Entity → Entity
    "COMPARED_WITH": (None, None),  # Entity → Entity
    "IMPROVES": (None, None),  # Entity → Entity
    "WORSENS": (None, None),  # Entity → Entity
    "CORRELATES_WITH": (None, None),  # Entity → Entity
    "OTHER": (None, None),  # Entity → Entity
}

# V1 阶段由 Rule-based Validator 拦截的 relation_type（D-5）
# RECOMMENDED_BY：需要 Guideline/Consensus 实体，V1 暂无该类型
# OTHER：仅用于人工审核或 Ontology 扩展，不允许 LLM 自由生成（schema 层保留枚举，
#        校验层拦截；但若人工审核后插入 OTHER，则不拦截——这里按 D-5 仅拦截 RECOMMENDED_BY）
_V1_DISALLOWED_RELATION_TYPES: Final[frozenset[str]] = frozenset({"RECOMMENDED_BY"})


class RuleValidatorImpl:
    """业务规则校验器，实现 RuleValidator Protocol。

    无构造参数（纯函数式校验，无状态）。
    """

    def validate(
        self,
        evidences: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        document_id: str,
    ) -> list[ValidationIssue]:
        """对 evidences / entities / relations 做业务规则校验。

        参数：
            evidences   Evidence 列表（已分配 evidence_id）
            entities    Entity 列表（已分配 entity_id + 词典标准化）
            relations   Relation 列表（已分配 relation_id）
            document_id 当前文献 ID

        返回：
            ValidationIssue 列表（空=全部通过）。
        """
        issues: list[ValidationIssue] = []

        # 构建索引
        entity_map: dict[str, dict[str, Any]] = {}
        for ent in entities:
            eid = ent.get("entity_id", "")
            if eid:
                entity_map[eid] = ent

        evidence_map: dict[str, dict[str, Any]] = {}
        for ev in evidences:
            eid = ev.get("evidence_id", "")
            if eid:
                evidence_map[eid] = ev

        # 1. Evidence 校验（§14.4）
        issues += self._validate_evidences(evidences, document_id)

        # 2. Entity 校验（§14.2）
        issues += self._validate_entities(entities, evidence_map, document_id)

        # 3. Relation 校验（§10.1-§10.6 / §14.3 / D-5 / §22）
        issues += self._validate_relations(
            relations, entity_map, evidence_map, document_id
        )

        for _i in issues:
            _i.severity = severity_for(_i.error_code)
        return issues

    # -- Evidence 校验 ----------------------------------------------------- #
    def _validate_evidences(
        self,
        evidences: list[dict[str, Any]],
        document_id: str,
    ) -> list[ValidationIssue]:
        """§14.4：evidence_id 唯一 + source_text 存在 + document_id 一致。"""
        issues: list[ValidationIssue] = []
        seen_ids: set[str] = set()

        for ev in evidences:
            eid = str(ev.get("evidence_id", ""))
            # 唯一性
            if eid in seen_ids:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DUPLICATE_ENTITY,  # 复用：Evidence 重复
                        f"evidence_id 重复: {eid}",
                        "evidence_id",
                        eid,
                    )
                )
            seen_ids.add(eid)

            # document_id 一致性（§10.4）
            ev_doc = str(ev.get("document_id", ""))
            if ev_doc and ev_doc != document_id:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DOCUMENT_ID_MISMATCH,
                        f"Evidence.document_id={ev_doc} 与当前文献 {document_id} 不一致",
                        "document_id",
                        eid,
                    )
                )

            # source_text 存在（§14.4）
            src = ev.get("source_text", "")
            if not src or not str(src).strip():
                issues.append(
                    ValidationIssue(
                        ErrorCode.SOURCE_TEXT_MISSING,
                        "Evidence.source_text 为空",
                        "source_text",
                        eid,
                    )
                )

            # evidence_statement 存在
            stmt = ev.get("evidence_statement", "")
            if not stmt or not str(stmt).strip():
                issues.append(
                    ValidationIssue(
                        ErrorCode.SOURCE_TEXT_MISSING,
                        "Evidence.evidence_statement 为空",
                        "evidence_statement",
                        eid,
                    )
                )

        for _i in issues:
            _i.severity = severity_for(_i.error_code)
        return issues

    # -- Entity 校验 ------------------------------------------------------- #
    def _validate_entities(
        self,
        entities: list[dict[str, Any]],
        evidence_map: dict[str, dict[str, Any]],
        document_id: str,
    ) -> list[ValidationIssue]:
        """§14.2：entity_id 唯一 + source_text 存在 + evidence_id 存在 + document_id 一致。"""
        issues: list[ValidationIssue] = []
        seen_ids: set[str] = set()

        for ent in entities:
            eid = str(ent.get("entity_id", ""))

            # 唯一性
            if eid in seen_ids:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DUPLICATE_ENTITY,
                        f"entity_id 重复: {eid}",
                        "entity_id",
                        eid,
                    )
                )
            seen_ids.add(eid)

            # document_id 一致性
            ent_doc = str(ent.get("document_id", ""))
            if ent_doc and ent_doc != document_id:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DOCUMENT_ID_MISMATCH,
                        f"Entity.document_id={ent_doc} 与当前文献 {document_id} 不一致",
                        "document_id",
                        eid,
                    )
                )

            # source_text 存在（§14.2）
            src = ent.get("source_text", "")
            if not src or not str(src).strip():
                issues.append(
                    ValidationIssue(
                        ErrorCode.SOURCE_TEXT_MISSING,
                        "Entity.source_text 为空",
                        "source_text",
                        eid,
                    )
                )

            # mention 存在
            mention = ent.get("mention", "")
            if not mention or not str(mention).strip():
                issues.append(
                    ValidationIssue(
                        ErrorCode.SOURCE_TEXT_MISSING,
                        "Entity.mention 为空",
                        "mention",
                        eid,
                    )
                )

            # evidence_ids 存在性（§14.2：evidence_id 存在时能找到对应 Evidence）
            ev_ids = ent.get("evidence_ids", [])
            if not isinstance(ev_ids, list) or not ev_ids:
                issues.append(
                    ValidationIssue(
                        ErrorCode.MISSING_REQUIRED_FIELD,
                        "Entity.evidence_ids 为空或非数组（至少需要 1 条 Evidence 支持）",
                        "evidence_ids",
                        eid,
                    )
                )
            else:
                for ev_id in ev_ids:
                    if ev_id not in evidence_map:
                        issues.append(
                            ValidationIssue(
                                ErrorCode.EVIDENCE_NOT_FOUND,
                                f"Entity 引用了不存在的 evidence_id: {ev_id}",
                                "evidence_ids",
                                eid,
                            )
                        )

        for _i in issues:
            _i.severity = severity_for(_i.error_code)
        return issues

    # -- Relation 校验 ----------------------------------------------------- #
    def _validate_relations(
        self,
        relations: list[dict[str, Any]],
        entity_map: dict[str, dict[str, Any]],
        evidence_map: dict[str, dict[str, Any]],
        document_id: str,
    ) -> list[ValidationIssue]:
        """§10.1-§10.6 / §14.3 / D-5 / §22：Relation 全套业务规则校验。"""
        issues: list[ValidationIssue] = []
        seen_ids: set[str] = set()

        for rel in relations:
            rid = str(rel.get("relation_id", ""))

            # 唯一性（§14.3）
            if rid in seen_ids:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DUPLICATE_RELATION,
                        f"relation_id 重复: {rid}",
                        "relation_id",
                        rid,
                    )
                )
            seen_ids.add(rid)

            # document_id 一致性（§10.2）
            rel_doc = str(rel.get("document_id", ""))
            if rel_doc and rel_doc != document_id:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DOCUMENT_ID_MISMATCH,
                        f"Relation.document_id={rel_doc} 与当前文献 {document_id} 不一致",
                        "document_id",
                        rid,
                    )
                )

            # D-5：RECOMMENDED_BY 拦截（V1 阶段）
            rtype = str(rel.get("relation_type", ""))
            if rtype in _V1_DISALLOWED_RELATION_TYPES:
                issues.append(
                    ValidationIssue(
                        ErrorCode.UNSUPPORTED_RELATION,
                        f"V1 阶段不允许 relation_type={rtype}（D-5 拦截："
                        f"需要 Guideline/Consensus 实体，当前体系暂无）",
                        "relation_type",
                        rid,
                    )
                )

            # §22：自环检查（head == tail）
            head_id = str(rel.get("head_entity_id", ""))
            tail_id = str(rel.get("tail_entity_id", ""))
            if head_id and tail_id and head_id == tail_id:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DOMAIN_RANGE_MISMATCH,
                        f"head_entity_id 与 tail_entity_id 相同（{head_id}），禁止自环",
                        "head_entity_id/tail_entity_id",
                        rid,
                    )
                )

            # §10.1：Entity 存在性（head + tail）
            head_ent = entity_map.get(head_id)
            if head_ent is None:
                issues.append(
                    ValidationIssue(
                        ErrorCode.ENTITY_NOT_FOUND,
                        f"head_entity_id={head_id} 不存在于 Entity 数据集中",
                        "head_entity_id",
                        rid,
                    )
                )
            tail_ent = entity_map.get(tail_id)
            if tail_ent is None:
                issues.append(
                    ValidationIssue(
                        ErrorCode.ENTITY_NOT_FOUND,
                        f"tail_entity_id={tail_id} 不存在于 Entity 数据集中",
                        "tail_entity_id",
                        rid,
                    )
                )

            # §10.2：Head/Tail Entity 的 document_id 一致性
            if head_ent and str(head_ent.get("document_id", "")) != document_id:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DOCUMENT_ID_MISMATCH,
                        f"Head Entity.document_id={head_ent.get('document_id')} "
                        f"与 Relation.document_id={document_id} 不一致",
                        "head_entity_id",
                        rid,
                    )
                )
            if tail_ent and str(tail_ent.get("document_id", "")) != document_id:
                issues.append(
                    ValidationIssue(
                        ErrorCode.DOCUMENT_ID_MISMATCH,
                        f"Tail Entity.document_id={tail_ent.get('document_id')} "
                        f"与 Relation.document_id={document_id} 不一致",
                        "tail_entity_id",
                        rid,
                    )
                )

            # §10.5：Domain/Range 检查
            if head_ent and tail_ent and rtype in _DOMAIN_RANGE:
                head_types, tail_types = _DOMAIN_RANGE[rtype]
                head_etype = str(head_ent.get("entity_type", ""))
                tail_etype = str(tail_ent.get("entity_type", ""))
                # None 表示通配（Entity → Entity）
                if head_types is not None and head_etype not in head_types:
                    issues.append(
                        ValidationIssue(
                            ErrorCode.DOMAIN_RANGE_MISMATCH,
                            f"relation_type={rtype} 要求 Head 为 {sorted(head_types)}，"
                            f"实际为 {head_etype}",
                            "head_entity_id",
                            rid,
                        )
                    )
                if tail_types is not None and tail_etype not in tail_types:
                    issues.append(
                        ValidationIssue(
                            ErrorCode.DOMAIN_RANGE_MISMATCH,
                            f"relation_type={rtype} 要求 Tail 为 {sorted(tail_types)}，"
                            f"实际为 {tail_etype}",
                            "tail_entity_id",
                            rid,
                        )
                    )

            # §10.3：Evidence 存在性
            ev_ids = rel.get("evidence_ids", [])
            if not isinstance(ev_ids, list) or not ev_ids:
                issues.append(
                    ValidationIssue(
                        ErrorCode.MISSING_REQUIRED_FIELD,
                        "Relation.evidence_ids 为空或非数组（至少需要 1 条 Evidence 支持）",
                        "evidence_ids",
                        rid,
                    )
                )
            else:
                for ev_id in ev_ids:
                    if ev_id not in evidence_map:
                        issues.append(
                            ValidationIssue(
                                ErrorCode.EVIDENCE_NOT_FOUND,
                                f"Relation 引用了不存在的 evidence_id: {ev_id}",
                                "evidence_ids",
                                rid,
                            )
                        )

            # §10.6：Evidence 支持检查（Relation 应能溯源至 Evidence.source_text）
            # 轻量检查：若 Relation 关联的所有 Evidence 的 source_text 都为空，则标记
            # 完整的溯源（Relation 语义在 source_text 中有依据）需人工/NLP 判断
            if isinstance(ev_ids, list) and ev_ids:
                all_empty = True
                for ev_id in ev_ids:
                    ev = evidence_map.get(ev_id)
                    if ev and str(ev.get("source_text", "")).strip():
                        all_empty = False
                        break
                if all_empty:
                    issues.append(
                        ValidationIssue(
                            ErrorCode.MANUAL_REVIEW_REQUIRED,
                            "Relation 关联的所有 Evidence.source_text 为空，无法溯源",
                            "evidence_ids",
                            rid,
                        )
                    )

        for _i in issues:
            _i.severity = severity_for(_i.error_code)
        return issues


# --------------------------------------------------------------------------- #
# 命令行入口（自检）
# --------------------------------------------------------------------------- #
def _main() -> int:
    """自检：用合法/非法样例验证各错误码触发。"""
    print("=" * 80)
    print("P7 Rule Validator 自检")
    print("=" * 80)

    validator = RuleValidatorImpl()
    assert isinstance(validator, RuleValidator), "不满足 RuleValidator Protocol"
    print("✓ isinstance(validator, RuleValidator) = True")

    # 合法样例
    evidences = [
        {
            "evidence_id": "BT000001-EV-test0001",
            "document_id": "BT000001",
            "evidence_type": "Imaging Finding",
            "evidence_statement": "Restricted diffusion on DWI",
            "source_text": "Restricted diffusion was observed on DWI",
            "section": "Results",
            "page": 1,
            "assertion_type": "Positive",
            "entities": [],
        },
    ]
    entities = [
        {
            "entity_id": "BT000001-ENT-aaaaaaaa",
            "document_id": "BT000001",
            "entity_type": "Disease",
            "mention": "stroke",
            "canonical_name": None,
            "ontology_id": None,
            "source_text": "acute stroke",
            "page": 1,
            "section": "Abstract",
            "evidence_ids": ["BT000001-EV-test0001"],
        },
        {
            "entity_id": "BT000001-ENT-bbbbbbbb",
            "document_id": "BT000001",
            "entity_type": "ImagingFinding",
            "mention": "restricted diffusion",
            "canonical_name": None,
            "ontology_id": None,
            "source_text": "Restricted diffusion",
            "page": 1,
            "section": "Results",
            "evidence_ids": ["BT000001-EV-test0001"],
        },
    ]
    relations = [
        {
            "relation_id": "BT000001-R-test0001",
            "document_id": "BT000001",
            "head_entity_id": "BT000001-ENT-aaaaaaaa",
            "relation_type": "HAS_FINDING",
            "tail_entity_id": "BT000001-ENT-bbbbbbbb",
            "assertion_type": "Positive",
            "evidence_ids": ["BT000001-EV-test0001"],
        },
    ]

    issues = validator.validate(evidences, entities, relations, "BT000001")
    assert not issues, f"合法样例应通过，但有问题: {issues}"
    print("✓ 合法样例通过")

    # 1. DOMAIN_RANGE_MISMATCH
    bad_relations = list(relations)
    bad_relations[0] = dict(relations[0])
    bad_relations[0]["head_entity_id"] = "BT000001-ENT-bbbbbbbb"  # ImagingFinding
    bad_relations[0]["tail_entity_id"] = "BT000001-ENT-aaaaaaaa"  # Disease
    # HAS_FINDING 要求 Disease → ImagingFinding，反了
    issues = validator.validate(evidences, entities, bad_relations, "BT000001")
    assert any(i.error_code == ErrorCode.DOMAIN_RANGE_MISMATCH for i in issues)
    print(f"✓ Domain/Range 不匹配 → DOMAIN_RANGE_MISMATCH（{len(issues)} 个）")

    # 2. ENTITY_NOT_FOUND
    bad_relations2 = list(relations)
    bad_relations2[0] = dict(relations[0])
    bad_relations2[0]["tail_entity_id"] = "BT000001-ENT-fake0000"  # 不存在
    issues = validator.validate(evidences, entities, bad_relations2, "BT000001")
    assert any(i.error_code == ErrorCode.ENTITY_NOT_FOUND for i in issues)
    print(f"✓ tail_entity_id 不存在 → ENTITY_NOT_FOUND（{len(issues)} 个）")

    # 3. EVIDENCE_NOT_FOUND
    bad_relations3 = list(relations)
    bad_relations3[0] = dict(relations[0])
    bad_relations3[0]["evidence_ids"] = ["BT000001-EV-fake0000"]
    issues = validator.validate(evidences, entities, bad_relations3, "BT000001")
    assert any(i.error_code == ErrorCode.EVIDENCE_NOT_FOUND for i in issues)
    print(f"✓ evidence_id 不存在 → EVIDENCE_NOT_FOUND（{len(issues)} 个）")

    # 4. DOCUMENT_ID_MISMATCH
    bad_relations4 = list(relations)
    bad_relations4[0] = dict(relations[0])
    bad_relations4[0]["document_id"] = "BT000099"
    issues = validator.validate(evidences, entities, bad_relations4, "BT000001")
    assert any(i.error_code == ErrorCode.DOCUMENT_ID_MISMATCH for i in issues)
    print(f"✓ document_id 不一致 → DOCUMENT_ID_MISMATCH（{len(issues)} 个）")

    # 5. UNSUPPORTED_RELATION (D-5)
    bad_relations5 = list(relations)
    bad_relations5[0] = dict(relations[0])
    bad_relations5[0]["relation_type"] = "RECOMMENDED_BY"
    issues = validator.validate(evidences, entities, bad_relations5, "BT000001")
    assert any(i.error_code == ErrorCode.UNSUPPORTED_RELATION for i in issues)
    print(f"✓ RECOMMENDED_BY → UNSUPPORTED_RELATION（D-5 拦截，{len(issues)} 个）")

    # 6. SOURCE_TEXT_MISSING
    bad_evidences = [dict(evidences[0])]
    bad_evidences[0]["source_text"] = ""
    issues = validator.validate(bad_evidences, entities, relations, "BT000001")
    assert any(i.error_code == ErrorCode.SOURCE_TEXT_MISSING for i in issues)
    print(f"✓ source_text 为空 → SOURCE_TEXT_MISSING（{len(issues)} 个）")

    # 7. 自环检查
    bad_relations6 = list(relations)
    bad_relations6[0] = dict(relations[0])
    bad_relations6[0]["relation_type"] = "ASSOCIATED_WITH"
    bad_relations6[0]["tail_entity_id"] = bad_relations6[0]["head_entity_id"]
    issues = validator.validate(evidences, entities, bad_relations6, "BT000001")
    assert any(i.error_code == ErrorCode.DOMAIN_RANGE_MISMATCH for i in issues)
    print(f"✓ 自环（head==tail）→ DOMAIN_RANGE_MISMATCH（{len(issues)} 个）")

    print("\n自检全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
