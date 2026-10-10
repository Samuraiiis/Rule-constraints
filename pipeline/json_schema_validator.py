"""JSON Schema 结构校验器（实现 single_doc_runner.JSONSchemaValidator 协议）。

基于 schemas/*.schema.json 对 Evidence / Entity / Relation 做结构校验
（Schema_rules §14.1）。

检查项：
    1. JSON 格式（dict 类型）
    2. required 字段齐全
    3. 数据类型（string/integer/array/object/null）
    4. enum 枚举值合法
    5. additionalProperties（不允许额外字段）
    6. minLength / minItems / uniqueItems / minimum

使用 jsonschema 库（Draft 2020-12）做实际校验，将校验失败映射为
ValidationIssue（error_code=SCHEMA_VALIDATION_FAILED）。

输入 / 输出：
    输入：instance dict + schema_name ∈ {'evidence','entity','relation'}
    输出：list[ValidationIssue]（空=通过）

命令示例：
    # 自检
    python -m pipeline.json_schema_validator
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Final

from pipeline.single_doc_runner import JSONSchemaValidator, ValidationIssue, severity_for
from pipeline.state_manager import ErrorCode

# schemas/ 目录（与 single_doc_runner.SCHEMAS_DIR 一致）
SCHEMAS_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "schemas"

# 支持的 schema 名称
_VALID_SCHEMA_NAMES: Final[frozenset[str]] = frozenset({"evidence", "entity", "relation"})


class JSONSchemaValidatorImpl:
    """JSON Schema 结构校验器，实现 JSONSchemaValidator Protocol。

    构造参数：
        schemas_dir  schemas/ 目录路径（默认 pipeline 父目录的 schemas/）
    """

    def __init__(self, schemas_dir: Path | None = None) -> None:
        self.schemas_dir = schemas_dir or SCHEMAS_DIR
        # 惰性加载：schema_name → 解析后的 schema dict
        self._cache: dict[str, dict[str, Any]] = {}

    def validate(
        self,
        instance: dict[str, Any],
        schema_name: str,
    ) -> list[ValidationIssue]:
        """对 instance 做 JSON Schema 校验。

        参数：
            instance     待校验的 dict（一条 Evidence / Entity / Relation）
            schema_name  'evidence' / 'entity' / 'relation'

        返回：
            ValidationIssue 列表（空=通过）。
            每条 issue 的 error_code = SCHEMA_VALIDATION_FAILED。
        """
        if schema_name not in _VALID_SCHEMA_NAMES:
            return [
                ValidationIssue(
                    ErrorCode.SCHEMA_VALIDATION_FAILED,
                    f"未知的 schema_name: {schema_name}，"
                    f"允许值: {sorted(_VALID_SCHEMA_NAMES)}",
                    "schema_name",
                )
            ]

        # 加载 schema
        try:
            schema = self._load_schema(schema_name)
        except FileNotFoundError as exc:
            return [
                ValidationIssue(
                    ErrorCode.SCHEMA_VALIDATION_FAILED,
                    f"schema 文件未找到: {exc}",
                    "schema_name",
                )
            ]
        except json.JSONDecodeError as exc:
            return [
                ValidationIssue(
                    ErrorCode.SCHEMA_VALIDATION_FAILED,
                    f"schema 文件 JSON 解析失败: {exc}",
                    "schema_name",
                )
            ]

        # 基本类型检查（instance 必须是 dict）
        if not isinstance(instance, dict):
            return [
                ValidationIssue(
                    ErrorCode.SCHEMA_VALIDATION_FAILED,
                    f"期望 JSON 对象，得到 {type(instance).__name__}",
                    "instance",
                )
            ]

        # jsonschema 校验
        import jsonschema

        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))

        if not errors:
            return []

        issues: list[ValidationIssue] = []
        for err in errors:
            # 构造字段路径（如 "entities.0.evidence_ids"）
            field_path = _format_field_path(err.path)
            issues.append(
                ValidationIssue(
                    ErrorCode.SCHEMA_VALIDATION_FAILED,
                    err.message,
                    field_path,
                    _get_id_for_ref(instance, schema_name),
                )
            )
        for _i in issues:
            _i.severity = severity_for(_i.error_code)
        return issues

    # -- 内部辅助 ----------------------------------------------------------- #
    def _load_schema(self, schema_name: str) -> dict[str, Any]:
        """惰性加载并缓存 schema 文件。"""
        if schema_name in self._cache:
            return self._cache[schema_name]
        path = self.schemas_dir / f"{schema_name}.schema.json"
        if not path.exists():
            raise FileNotFoundError(f"schema 文件不存在: {path}")
        schema = json.loads(path.read_text(encoding="utf-8"))
        self._cache[schema_name] = schema
        return schema


def _format_field_path(path: Any) -> str:
    """将 jsonschema 的 deque path 格式化为字符串。"""
    parts = list(path)
    if not parts:
        return ""
    return ".".join(str(p) for p in parts)


def _get_id_for_ref(instance: dict[str, Any], schema_name: str) -> str:
    """从 instance 中提取 ID 字段供 ref 标识。"""
    id_field = {
        "evidence": "evidence_id",
        "entity": "entity_id",
        "relation": "relation_id",
    }.get(schema_name, "")
    if id_field:
        return str(instance.get(id_field, ""))
    return ""


# --------------------------------------------------------------------------- #
# 命令行入口（自检）
# --------------------------------------------------------------------------- #
def _main() -> int:
    """自检：用 schemas/*.schema.json 校验合法/非法样例。"""
    print("=" * 80)
    print("P7 JSON Schema Validator 自检")
    print("=" * 80)

    validator = JSONSchemaValidatorImpl()

    # 检查 Protocol 契约
    assert isinstance(validator, JSONSchemaValidator), "不满足 JSONSchemaValidator Protocol"
    print("✓ isinstance(validator, JSONSchemaValidator) = True")

    # 1. 合法 Evidence
    valid_evidence = {
        "evidence_id": "BT000001-EV-test0001",
        "document_id": "BT000001",
        "evidence_type": "Imaging Finding",
        "evidence_statement": "test statement",
        "source_text": "test source",
        "section": "Results",
        "page": 1,
        "assertion_type": "Positive",
        "entities": [],
    }
    issues = validator.validate(valid_evidence, "evidence")
    assert not issues, f"合法 Evidence 应通过，但有问题: {issues}"
    print("✓ 合法 Evidence 通过")

    # 2. 非法 Evidence（缺必填字段）
    invalid_evidence = dict(valid_evidence)
    del invalid_evidence["source_text"]
    issues = validator.validate(invalid_evidence, "evidence")
    assert issues, "缺 source_text 应失败"
    assert all(i.error_code == ErrorCode.SCHEMA_VALIDATION_FAILED for i in issues)
    print(f"✓ 缺 source_text → {len(issues)} 个 SCHEMA_VALIDATION_FAILED")

    # 3. 非法 enum
    invalid_enum = dict(valid_evidence)
    invalid_enum["assertion_type"] = "InvalidValue"
    issues = validator.validate(invalid_enum, "evidence")
    assert issues
    print(f"✓ 非法 enum → {len(issues)} 个 SCHEMA_VALIDATION_FAILED")

    # 4. 合法 Entity
    valid_entity = {
        "entity_id": "BT000001-ENT-test0001",
        "document_id": "BT000001",
        "entity_type": "Disease",
        "mention": "stroke",
        "canonical_name": None,
        "ontology_id": None,
        "source_text": "acute stroke",
        "page": 1,
        "section": "Abstract",
        "evidence_ids": ["BT000001-EV-test0001"],
    }
    issues = validator.validate(valid_entity, "entity")
    assert not issues, f"合法 Entity 应通过: {issues}"
    print("✓ 合法 Entity 通过")

    # 5. 合法 Relation
    valid_relation = {
        "relation_id": "BT000001-R-test0001",
        "document_id": "BT000001",
        "head_entity_id": "BT000001-ENT-test0001",
        "relation_type": "HAS_FINDING",
        "tail_entity_id": "BT000001-ENT-test0002",
        "assertion_type": "Positive",
        "evidence_ids": ["BT000001-EV-test0001"],
    }
    issues = validator.validate(valid_relation, "relation")
    assert not issues, f"合法 Relation 应通过: {issues}"
    print("✓ 合法 Relation 通过")

    # 6. additionalProperties 检查
    extra_field = dict(valid_relation)
    extra_field["extra_field"] = "not allowed"
    issues = validator.validate(extra_field, "relation")
    assert issues
    print(f"✓ additionalProperties → {len(issues)} 个 SCHEMA_VALIDATION_FAILED")

    print("\n自检全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
