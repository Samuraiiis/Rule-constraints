"""文档级状态机与检查点（Schema_rules §17 批处理状态 + §18 版本管理 + §16 错误码）。

状态机（§17）：

    PENDING → PROCESSING → SUCCESS
                       ↘ FAILED → RETRY (retry_count < MAX_RETRIES) → PROCESSING
                                ↘ MANUAL_REVIEW（重试耗尽 / 不可重试错误）

检查点（用户硬约束：增量保存进度，防止中途中断丢失数据）：
    每完成一个抽取阶段即原子落盘 checkpoint.json + 阶段产物 JSON；
    重试时从最近已完成阶段恢复，无需重跑整篇文献。

版本管理（§18）：
    schema_version / extractor_version / model 三元组标识一次抽取运行；
    不同版本产物存于 data/intermediate/{doc_id}.v{N}/，互不覆盖。
    相同三元组的重试复用同一版本目录；三元组变更则新建下一版本号。

错误码（§16）在本模块定义，供本文件重试分类使用，亦供 extractors / validators
（P4-P7）通过 ``from pipeline.state_manager import ErrorCode`` 复用。

输入 / 输出：
    输入：document_id、版本三元组、data_dir 根目录
    输出：data/intermediate/{doc_id}.v{N}/checkpoint.json 及阶段产物路径
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------- #
# 错误码（Schema_rules §16，共 14 个）
# --------------------------------------------------------------------------- #
class ErrorCode(str, Enum):
    """Schema_rules §16 定义的全部错误码。"""

    INVALID_JSON = "INVALID_JSON"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_ENUM = "INVALID_ENUM"
    DUPLICATE_ENTITY = "DUPLICATE_ENTITY"
    DUPLICATE_RELATION = "DUPLICATE_RELATION"
    ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    DOCUMENT_ID_MISMATCH = "DOCUMENT_ID_MISMATCH"
    DOMAIN_RANGE_MISMATCH = "DOMAIN_RANGE_MISMATCH"
    SOURCE_TEXT_MISSING = "SOURCE_TEXT_MISSING"
    UNSUPPORTED_RELATION = "UNSUPPORTED_RELATION"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


# 可重试错误：LLM 输出层面问题，重跑可能修正
RETRYABLE_ERRORS: Final[frozenset[ErrorCode]] = frozenset(
    {
        ErrorCode.INVALID_JSON,
        ErrorCode.SCHEMA_VALIDATION_FAILED,
        ErrorCode.MISSING_REQUIRED_FIELD,
        ErrorCode.INVALID_ENUM,
        ErrorCode.NORMALIZATION_FAILED,
    }
)

# 不可重试错误：逻辑 / 数据质量 / 引用完整性问题，直接进入人工审核
UNRETRYABLE_ERRORS: Final[frozenset[ErrorCode]] = frozenset(
    {
        ErrorCode.DUPLICATE_ENTITY,
        ErrorCode.DUPLICATE_RELATION,
        ErrorCode.ENTITY_NOT_FOUND,
        ErrorCode.EVIDENCE_NOT_FOUND,
        ErrorCode.DOCUMENT_ID_MISMATCH,
        ErrorCode.DOMAIN_RANGE_MISMATCH,
        ErrorCode.SOURCE_TEXT_MISSING,
        ErrorCode.UNSUPPORTED_RELATION,
        ErrorCode.MANUAL_REVIEW_REQUIRED,
    }
)


# --------------------------------------------------------------------------- #
# 文档状态（§17）
# --------------------------------------------------------------------------- #
class DocState(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


# --------------------------------------------------------------------------- #
# 抽取阶段（检查点粒度）
# --------------------------------------------------------------------------- #
class Stage(str, Enum):
    """单文档流水线阶段，顺序见 STAGE_ORDER。"""

    METADATA = "METADATA"
    EVIDENCE = "EVIDENCE"        # D-2 阶段 A：LLM 抽 Evidence（entities=[]）
    ENTITY = "ENTITY"            # D-2 阶段 B：LLM 抽 Entity（填 evidence_ids）
    BACKFILL = "BACKFILL"        # D-2 阶段 C：Python 反向回填 Evidence.entities
    RELATION = "RELATION"        # LLM 抽 Relation
    VALIDATION = "VALIDATION"    # JSON Schema + Rule-based 校验
    PERSIST = "PERSIST"          # 落盘至 final CSV


STAGE_ORDER: Final[tuple[Stage, ...]] = (
    Stage.METADATA,
    Stage.EVIDENCE,
    Stage.ENTITY,
    Stage.BACKFILL,
    Stage.RELATION,
    Stage.VALIDATION,
    Stage.PERSIST,
)


# --------------------------------------------------------------------------- #
# 检查点数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Checkpoint:
    """单文档运行检查点，序列化为 checkpoint.json。"""

    document_id: str
    version: int = 1                       # 版本目录号 {doc_id}.v{version}
    state: DocState = DocState.PENDING
    stage: Stage | None = None             # 最近已完成阶段
    retry_count: int = 0
    last_error_code: ErrorCode | None = None
    last_error_msg: str = ""
    schema_version: str = ""
    extractor_version: str = ""
    model: str = ""
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    artifacts: dict[str, str] = field(default_factory=dict)  # stage -> 产物文件路径

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "version": self.version,
            "state": self.state.value,
            "stage": self.stage.value if self.stage else None,
            "retry_count": self.retry_count,
            "last_error_code": self.last_error_code.value if self.last_error_code else None,
            "last_error_msg": self.last_error_msg,
            "schema_version": self.schema_version,
            "extractor_version": self.extractor_version,
            "model": self.model,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "artifacts": dict(self.artifacts),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Checkpoint":
        return cls(
            document_id=d["document_id"],
            version=d.get("version", 1),
            state=DocState(d.get("state", "PENDING")),
            stage=Stage(d["stage"]) if d.get("stage") else None,
            retry_count=d.get("retry_count", 0),
            last_error_code=ErrorCode(d["last_error_code"]) if d.get("last_error_code") else None,
            last_error_msg=d.get("last_error_msg", ""),
            schema_version=d.get("schema_version", ""),
            extractor_version=d.get("extractor_version", ""),
            model=d.get("model", ""),
            started_at=d.get("started_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            artifacts=dict(d.get("artifacts", {})),
        )


# --------------------------------------------------------------------------- #
# 状态管理器
# --------------------------------------------------------------------------- #
MAX_RETRIES: Final[int] = 3  # §17：自动重试上限


class StateManager:
    """文档级状态机 + 检查点持久化。

    构造参数：
        data_dir           项目 data 根目录（其下含 intermediate/ final/ failed/）
        schema_version     Schema 版本（§18）
        extractor_version  抽取器版本（§18）
        model              LLM 模型标识（§18）
        max_retries        自动重试上限，默认 3
    """

    def __init__(
        self,
        data_dir: str | os.PathLike[str],
        schema_version: str,
        extractor_version: str,
        model: str,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.intermediate_dir = self.data_dir / "intermediate"
        self.final_dir = self.data_dir / "final"
        self.failed_dir = self.data_dir / "failed"
        self.schema_version = schema_version
        self.extractor_version = extractor_version
        self.model = model
        self.max_retries = max_retries

    # -- 路径 -----------------------------------------------------------------
    def _version_dir(self, document_id: str, version: int) -> Path:
        return self.intermediate_dir / f"{document_id}.v{version}"

    def _find_matching_version(self, document_id: str) -> tuple[int, Path] | None:
        """纯查找：返回与当前版本三元组匹配的版本目录；无副作用，不创建目录。

        匹配条件：该版本目录的 checkpoint.json 中 schema_version /
        extractor_version / model 三者均与当前一致（支持断点续跑 / 重试）。
        """
        prefix = f"{document_id}.v"
        if not self.intermediate_dir.exists():
            return None
        for entry in self.intermediate_dir.iterdir():
            if not entry.is_dir() or not entry.name.startswith(prefix):
                continue
            try:
                n = int(entry.name[len(prefix):])
            except ValueError:
                continue
            cp_file = entry / "checkpoint.json"
            if not cp_file.exists():
                continue
            try:
                data = json.loads(cp_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if (
                data.get("schema_version") == self.schema_version
                and data.get("extractor_version") == self.extractor_version
                and data.get("model") == self.model
            ):
                return n, entry
        return None

    def _next_version_number(self, document_id: str) -> int:
        """扫描已有 {doc}.v{N} 目录，返回下一版本号。"""
        if not self.intermediate_dir.exists():
            return 1
        prefix = f"{document_id}.v"
        highest = 0
        for entry in self.intermediate_dir.iterdir():
            if not entry.is_dir() or not entry.name.startswith(prefix):
                continue
            try:
                n = int(entry.name[len(prefix):])
            except ValueError:
                continue
            highest = max(highest, n)
        return highest + 1

    def _create_version_dir(self, document_id: str, version: int) -> Path:
        vdir = self._version_dir(document_id, version)
        vdir.mkdir(parents=True, exist_ok=True)
        return vdir

    def _checkpoint_path(self, version_dir: Path) -> Path:
        return version_dir / "checkpoint.json"

    def artifact_path(self, cp: Checkpoint, stage: Stage, ext: str = "json") -> Path:
        """返回某阶段产物文件路径（供 runner 落盘中间产物）。

        使用 cp.version 直接定位版本目录，避免重复扫描与误建目录。
        """
        vdir = self._version_dir(cp.document_id, cp.version)
        vdir.mkdir(parents=True, exist_ok=True)
        return vdir / f"{stage.value.lower()}.{ext}"

    # -- 读写 -----------------------------------------------------------------
    def load_checkpoint(self, document_id: str) -> Checkpoint | None:
        """加载匹配当前版本三元组的检查点；不存在或版本不匹配返回 None。"""
        matched = self._find_matching_version(document_id)
        if matched is None:
            return None
        version, vdir = matched
        cp_file = self._checkpoint_path(vdir)
        try:
            data = json.loads(cp_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        cp = Checkpoint.from_dict(data)
        cp.version = version
        return cp

    def save_checkpoint(self, cp: Checkpoint) -> Path:
        """原子写检查点（先写临时文件再 os.replace，防止中途崩溃损坏）。"""
        vdir = self._version_dir(cp.document_id, cp.version)
        vdir.mkdir(parents=True, exist_ok=True)
        cp.updated_at = time.time()
        cp_file = self._checkpoint_path(vdir)
        tmp = cp_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(cp.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, cp_file)
        return cp_file

    # -- 状态流转 -------------------------------------------------------------
    def start(self, document_id: str) -> Checkpoint:
        """开始 / 续跑一篇文献：返回 PROCESSING 检查点。

        匹配三元组的版本目录存在 → 复用（断点续跑 / 重试）；
        否则新建下一版本号（互不覆盖，§18）。
        """
        matched = self._find_matching_version(document_id)
        if matched is not None:
            version, _ = matched
            cp = self.load_checkpoint(document_id)
            if cp is None:
                # 目录存在但 checkpoint 损坏 → 在同一版本号下重建
                cp = Checkpoint(
                    document_id=document_id,
                    version=version,
                    state=DocState.PROCESSING,
                    schema_version=self.schema_version,
                    extractor_version=self.extractor_version,
                    model=self.model,
                )
            cp.version = version
        else:
            version = self._next_version_number(document_id)
            self._create_version_dir(document_id, version)
            cp = Checkpoint(
                document_id=document_id,
                version=version,
                state=DocState.PROCESSING,
                schema_version=self.schema_version,
                extractor_version=self.extractor_version,
                model=self.model,
            )
        cp.state = DocState.PROCESSING
        cp.last_error_code = None
        cp.last_error_msg = ""
        self.save_checkpoint(cp)
        return cp

    def complete_stage(
        self,
        cp: Checkpoint,
        stage: Stage,
        artifact_path: str | os.PathLike[str] | None = None,
    ) -> Checkpoint:
        """记录某阶段完成并落盘。"""
        cp.stage = stage
        if artifact_path is not None:
            cp.artifacts[stage.value] = str(artifact_path)
        self.save_checkpoint(cp)
        return cp

    def next_stage(self, cp: Checkpoint) -> Stage | None:
        """返回下一未完成阶段；全部完成返回 None。"""
        if cp.stage is None:
            return STAGE_ORDER[0]
        try:
            idx = STAGE_ORDER.index(cp.stage)
        except ValueError:
            return STAGE_ORDER[0]
        if idx + 1 >= len(STAGE_ORDER):
            return None
        return STAGE_ORDER[idx + 1]

    def can_retry(self, cp: Checkpoint) -> bool:
        """是否仍可自动重试。"""
        return cp.retry_count < self.max_retries and cp.last_error_code in RETRYABLE_ERRORS

    def mark_failed(
        self,
        cp: Checkpoint,
        error_code: ErrorCode,
        message: str,
    ) -> Checkpoint:
        """记录失败，并据错误码决定 RETRY 或 MANUAL_REVIEW。"""
        cp.last_error_code = error_code
        cp.last_error_msg = message
        if self.can_retry(cp):
            cp.retry_count += 1
            cp.state = DocState.RETRY
        else:
            cp.state = DocState.MANUAL_REVIEW
        self.save_checkpoint(cp)
        return cp

    def mark_retry(self, cp: Checkpoint) -> Checkpoint:
        """RETRY → PROCESSING，准备重跑（从 next_stage 恢复）。"""
        cp.state = DocState.PROCESSING
        self.save_checkpoint(cp)
        return cp

    def mark_success(self, cp: Checkpoint) -> Checkpoint:
        """全部阶段完成，标记 SUCCESS。"""
        cp.state = DocState.SUCCESS
        cp.last_error_code = None
        cp.last_error_msg = ""
        self.save_checkpoint(cp)
        return cp


# --------------------------------------------------------------------------- #
# 命令行自检
# --------------------------------------------------------------------------- #
def _main() -> int:
    """命令行自检入口。

    用法：
        python -m pipeline.state_manager <document_id> [data_dir]

    示例：
        python -m pipeline.state_manager CV001886 ./data
    """
    if len(sys.argv) < 2:
        print("用法: python -m pipeline.state_manager <document_id> [data_dir]")
        return 2
    # 延迟 import 以避免本模块未作为包导入时失败
    doc_id = sys.argv[1]
    data_dir = sys.argv[2] if len(sys.argv) > 2 else "./data"
    sm = StateManager(data_dir, schema_version="1.2", extractor_version="0.1.0", model="self-test")
    cp = sm.start(doc_id)
    print("start        :", cp.state.value, "v" + str(cp.version))
    sm.complete_stage(cp, Stage.METADATA, None)
    print("after meta   :", cp.state.value, "stage=" + str(cp.stage))
    print("next stage   :", sm.next_stage(cp))
    sm.mark_failed(cp, ErrorCode.INVALID_JSON, "自检：模拟 LLM 返回非法 JSON")
    print("after fail   :", cp.state.value, "retry_count=" + str(cp.retry_count))
    print("can retry    :", sm.can_retry(cp))
    sm.mark_success(cp)
    print("after success:", cp.state.value)
    print("checkpoint   :", sm._checkpoint_path(sm._version_dir(doc_id, cp.version)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
