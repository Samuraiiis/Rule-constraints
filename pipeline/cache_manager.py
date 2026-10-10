"""缓存路径管理（支持模型版本目录隔离）。

不同 LLM 模型生成的抽取结果保存到不同版本目录，便于对比和升级：
    data/extracted/{RUN_VERSION}/{doc_id}_{suffix}.json

版本来源（优先级从高到低）：
    1. 环境变量 RUN_VERSION（.env 中设置，推荐显式指定）
    2. 从 LLM_MODEL 自动推导（如 deepseek-ai/DeepSeek-V4-Flash → v1_deepseek_v4_flash）

命令示例：
    python -c "from pipeline.cache_manager import get_cache_path; print(get_cache_path('BT000001', 'evidence'))"
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# 项目根目录（pipeline/ 的父目录）
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# 抽取结果根目录
_EXTRACTED_ROOT: Path = _PROJECT_ROOT / "data" / "extracted"

# 旧版缓存目录（无版本子目录，用于向后兼容回退读取）
_LEGACY_DIR: Path = _EXTRACTED_ROOT


def _load_env() -> None:
    """加载 .env 文件到 os.environ（已存在的不覆盖）。"""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def _derive_version_from_model(model: str) -> str:
    """从 LLM_MODEL 名称推导版本目录名。

    deepseek-ai/DeepSeek-V4-Flash → v1_deepseek_v4_flash
    gemini-2.0-flash               → v1_gemini_2_0_flash
    """
    # 取最后一段（/ 之后）
    name = model.rsplit("/", 1)[-1]
    # 转小写
    name = name.lower()
    # 非字母数字替换为下划线
    name = re.sub(r"[^a-z0-9]+", "_", name)
    # 去除首尾下划线
    name = name.strip("_")
    return f"v1_{name}"


def get_run_version() -> str:
    """获取当前运行版本目录名。

    优先级：环境变量 RUN_VERSION > 从 LLM_MODEL 推导
    """
    _load_env()
    version = os.environ.get("RUN_VERSION", "").strip()
    if version:
        return version
    model = os.environ.get("LLM_MODEL", "").strip()
    if model:
        return _derive_version_from_model(model)
    return "default"


def get_extract_dir(project_root: Path | None = None) -> Path:
    """获取抽取结果目录（含版本子目录）。

    返回: {project_root}/data/extracted/{RUN_VERSION}/
    """
    root = project_root or _PROJECT_ROOT
    return root / "data" / "extracted" / get_run_version()


def get_cache_path(
    doc_id: str,
    suffix: str,
    project_root: Path | None = None,
) -> Path:
    """获取缓存文件路径。

    参数：
        doc_id   文献 ID（如 BT000001）
        suffix   文件后缀（如 evidence / entity）
        project_root 项目根目录

    返回:
        {project_root}/data/extracted/{RUN_VERSION}/{doc_id}_{suffix}.json

    向后兼容: 如果版本目录下不存在，回退检查旧路径 data/extracted/{doc_id}_{suffix}.json
    """
    version_dir = get_extract_dir(project_root)
    new_path = version_dir / f"{doc_id}_{suffix}.json"
    if new_path.exists():
        return new_path

    # 向后兼容：旧版无版本目录的路径
    root = project_root or _PROJECT_ROOT
    legacy_path = root / "data" / "extracted" / f"{doc_id}_{suffix}.json"
    if legacy_path.exists():
        return legacy_path

    # 都不存在，返回新版路径（写入时用）
    return new_path


def ensure_dir(path: Path) -> Path:
    """确保目录存在，返回原路径。"""
    path.mkdir(parents=True, exist_ok=True)
    return path
