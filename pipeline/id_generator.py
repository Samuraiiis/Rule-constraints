"""确定性 ID 生成器（架构设计 D-1）。

ID 规则（基于 sha256 内容哈希，全局唯一，前缀 EV / ENT / R 互不冲突）：

    document_id   沿用 document_metadata.csv 现有值（如 CV001886），不由本模块生成
    evidence_id   = f"{document_id}-EV-{hash8(document_id, source_text)}"
    entity_id     = f"{document_id}-ENT-{hash8(document_id, mention, entity_type)}"
    relation_id   = f"{document_id}-R-{hash8(document_id, head_entity_id, relation_type, tail_entity_id)}"

去重语义（Schema_rules §15）：

    entity_id   基于 (mention, entity_type)        → 同文献同 mention+type 自动合并（§15.1）
    relation_id 基于 (head, relation_type, tail)   → 同一三元组自动合并（§15.2）

设计要点：

    1. 纯函数 + 确定性：相同输入永远产出相同 ID，保证重复运行可匹配、可去重。
    2. 哈希输入做轻量归一化（strip + 折叠内部连续空白为单空格），避免排版差异导致
       同一条证据 / 实体产生不同 ID。
    3. 多字段拼接使用 ASCII Unit Separator (\\x1f) 分隔，避免相邻字段边界歧义。
    4. 仅取 sha256 前 8 个十六进制字符（32 bit）；单文献内证据 / 实体规模远低于碰撞阈值。
    5. document_id 不在本模块生成；调用方须从 document_metadata.csv 透传。

输入 / 输出：
    输入：document_id (str) 与各对象内容字段
    输出：形如 "CV001886-EV-3f9a1c7d" 的稳定 ID 字符串

前置条件：document_id 符合 2字母+6数字 格式；各内容字段非空。

命令示例：
    python -m pipeline.id_generator CV001886 "Restricted diffusion was observed on DWI."
"""
from __future__ import annotations

import hashlib
import re
import sys
from typing import Final

# ID 类型前缀（互不冲突，便于按前缀路由存储与检索）
EVIDENCE_PREFIX: Final[str] = "EV"
ENTITY_PREFIX: Final[str] = "ENT"
RELATION_PREFIX: Final[str] = "R"

# sha256 截取长度（十六进制字符数）；8 char = 32 bit ≈ 4.3e9 取值空间
HASH_LEN: Final[int] = 8

# 字段分隔符：ASCII Unit Separator，正常医学文本 / 枚举值中不会出现，避免拼接歧义
_SEP: Final[str] = "\x1f"

# document_id 格式：2 字母分类前缀 + 6 位数字（如 BT000001 / CV001886 / ND000017）
_DOCUMENT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{2}\d{6}$")


def _normalize(text: str) -> str:
    """归一化文本用于哈希：去除首尾空白，折叠内部连续空白为单空格。"""
    if not isinstance(text, str):
        raise TypeError(f"哈希输入须为 str，收到 {type(text).__name__}")
    return " ".join(text.split())


def _hash8(*components: str) -> str:
    """对归一化后的字段拼接取 sha256 前 8 位十六进制。"""
    if not components:
        raise ValueError("哈希输入组件不能为空")
    blob = _SEP.join(_normalize(c) for c in components)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:HASH_LEN]


def is_valid_document_id(document_id: str) -> bool:
    """校验 document_id 是否符合 2字母+6数字 格式（如 CV001886）。"""
    return isinstance(document_id, str) and _DOCUMENT_ID_RE.match(document_id) is not None


def _require_document_id(document_id: str) -> None:
    """断言 document_id 非空且格式合法。"""
    if not isinstance(document_id, str) or not document_id:
        raise ValueError("document_id 不能为空")
    if not is_valid_document_id(document_id):
        raise ValueError(
            f"document_id 格式非法（应为 2字母+6数字，如 CV001886），收到 {document_id!r}"
        )


def make_evidence_id(document_id: str, source_text: str) -> str:
    """生成 evidence_id = {document_id}-EV-{hash8(document_id, source_text)}。

    基于 (document_id, source_text) 内容哈希；同一文献内相同原文 → 相同 evidence_id。
    """
    _require_document_id(document_id)
    if not source_text or not source_text.strip():
        raise ValueError("source_text 不能为空（Evidence_schema §7 要求可追溯原文）")
    return f"{document_id}-{EVIDENCE_PREFIX}-{_hash8(document_id, source_text)}"


def make_entity_id(document_id: str, mention: str, entity_type: str) -> str:
    """生成 entity_id = {document_id}-ENT-{hash8(document_id, mention, entity_type)}。

    基于 (document_id, mention, entity_type)；同一文献内同 mention+type 自动合并（§15.1）。
    """
    _require_document_id(document_id)
    if not mention or not mention.strip():
        raise ValueError("mention 不能为空（Entity_schema §4）")
    if not entity_type or not entity_type.strip():
        raise ValueError("entity_type 不能为空（Entity_schema §3）")
    return f"{document_id}-{ENTITY_PREFIX}-{_hash8(document_id, mention, entity_type)}"


def make_relation_id(
    document_id: str,
    head_entity_id: str,
    relation_type: str,
    tail_entity_id: str,
    assertion_type: str = "",
) -> str:
    """生成 relation_id = {document_id}-R-{hash8(document_id, head, type, tail, assertion)}。

    去重键为 (head_entity_id, relation_type, tail_entity_id, assertion_type)（§15.2）。
    assertion_type 必须参与去重：同一三元组的 Positive 与 Negative 是两条不同的
    医学断言（"X is associated with Y" vs "No association between X and Y"），
    合并会丢失否定结论。assertion_type 为空时保持旧行为（兼容旧调用方）。
    """
    _require_document_id(document_id)
    if not head_entity_id or not tail_entity_id:
        raise ValueError("head_entity_id / tail_entity_id 不能为空（Relation_schema §2）")
    if not relation_type or not relation_type.strip():
        raise ValueError("relation_type 不能为空（Relation_schema §3）")
    return (
        f"{document_id}-{RELATION_PREFIX}-"
        f"{_hash8(document_id, head_entity_id, relation_type, tail_entity_id, assertion_type)}"
    )


# --------------------------------------------------------------------------- #
# 命令行自检
# --------------------------------------------------------------------------- #
def _main() -> int:
    """命令行自检入口。

    用法：
        python -m pipeline.id_generator <document_id> <source_text>

    示例：
        python -m pipeline.id_generator CV001886 "Restricted diffusion on DWI."
    """
    if len(sys.argv) < 3:
        print("用法: python -m pipeline.id_generator <document_id> <source_text>")
        print("示例: python -m pipeline.id_generator CV001886 \"Restricted diffusion on DWI.\"")
        return 2
    doc_id, src = sys.argv[1], sys.argv[2]
    print("evidence_id :", make_evidence_id(doc_id, src))
    print("entity_id  :", make_entity_id(doc_id, "acute ischemic stroke", "Disease"))
    print("relation_id:", make_relation_id(doc_id, f"{doc_id}-ENT-aaaaaaaa", "HAS_FINDING", f"{doc_id}-ENT-bbbbbbbb"))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
