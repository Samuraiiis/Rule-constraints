"""OpenAI 兼容 LLM 客户端（httpx 封装，支持 JSON 模式）。

封装 OpenAI ``/v1/chat/completions`` 端点调用，兼容 OpenAI 官方、DeepSeek、
Qwen、Azure OpenAI 等任何遵循 OpenAI Chat Completions API 规范的服务。

核心功能：

    1. ``chat_json()`` —— 强制 ``response_format={"type": "json_object"}``，
       返回 LLM 响应文本（应为合法 JSON 字符串）。
    2. ``from_env()`` —— 从 .env 文件或环境变量构造（自动加载项目根 .env）。
    3. 错误分类：超时 / 限流 / 客户端错误 / 服务端错误，供上层重试决策。

配置方式（优先级从高到低）：
    构造参数 > 环境变量 > .env 文件

    在项目根目录创建 ``.env`` 文件，写入：
        LLM_API_KEY=sk-你的密钥
        LLM_BASE_URL=https://api.openai.com
        LLM_MODEL=gpt-4o-mini

    之后所有 ``LLMClient.from_env()`` 调用自动读取，无需手动设置环境变量。

命令示例：
    # 连通性测试
    python -m pipeline.llm_client

    # 单篇 Evidence 抽取测试（需先创建 .env）
    python -m pipeline.llm_client BT000001
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import httpx

from pipeline.cache_manager import ensure_dir, get_cache_path, get_run_version

# --------------------------------------------------------------------------- #
# .env 文件自动加载（无需 python-dotenv 依赖）
# --------------------------------------------------------------------------- #
def _load_env_file(env_path: Path | None = None) -> None:
    """读取 .env 文件，将 KEY=VALUE 设入 os.environ（已存在的环境变量不覆盖）。

    查找顺序：env_path 参数 > 项目根 .env（pipeline 父目录的 .env）
    """
    if env_path is None:
        # pipeline/ 的父目录 = 项目根
        env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


# --------------------------------------------------------------------------- #
# 默认参数
# --------------------------------------------------------------------------- #
DEFAULT_TIMEOUT: Final[float] = 300.0       # LLM 响应较慢，大文本需更久
DEFAULT_MAX_TOKENS: Final[int] = 8192       # 医学文献 Evidence 输出空间
DEFAULT_TEMPERATURE: Final[float] = 0.1     # 低温一致性
DEFAULT_API_VERSION: Final[str] = "v1"     # OpenAI API 版本路径


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class LLMError(Exception):
    """LLM 调用基础异常，携带 status_code / body 供上层分类重试。"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class LLMTimeoutError(LLMError):
    """请求超时（可重试）。"""


class LLMRateLimitError(LLMError):
    """429 限流（可重试，但需退避）。"""


class LLMClientError(LLMError):
    """4xx 客户端错误（通常不可重试，如 401 鉴权失败 / 400 参数错误）。"""


class LLMServerError(LLMError):
    """5xx 服务端错误（可重试）。"""


# --------------------------------------------------------------------------- #
# LLM 客户端
# --------------------------------------------------------------------------- #
class LLMClient:
    """OpenAI 兼容 Chat Completions 客户端。

    构造参数：
        api_key      API 密钥（环境变量 LLM_API_KEY 的默认值）
        base_url     API 基址（环境变量 LLM_BASE_URL 的默认值，如 https://api.openai.com）
        model        模型名（环境变量 LLM_MODEL 的默认值，如 gpt-4o）
        timeout      请求超时秒数
        max_tokens   响应最大 token 数
        temperature  采样温度
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> None:
        _load_env_file()  # 自动加载项目根 .env（若存在）
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "")
        self.timeout = timeout or float(os.environ.get("LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
        self.max_tokens = max_tokens or int(os.environ.get("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
        self.temperature = temperature if temperature is not None else float(os.environ.get("LLM_TEMPERATURE", str(DEFAULT_TEMPERATURE)))
        self.last_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置（环境变量或构造参数）")
        if not self.base_url:
            raise ValueError("LLM_BASE_URL 未配置（环境变量或构造参数）")
        if not self.model:
            raise ValueError("LLM_MODEL 未配置（环境变量或构造参数）")

        # 拼接 chat completions 端点 URL
        # 如果 base_url 已含 /v1 则直接用，否则自动拼接
        if self.base_url.endswith(f"/{DEFAULT_API_VERSION}"):
            self._endpoint = f"{self.base_url}/chat/completions"
        else:
            self._endpoint = f"{self.base_url}/{DEFAULT_API_VERSION}/chat/completions"

    @classmethod
    def from_env(cls) -> "LLMClient":
        """从 .env 文件 + 环境变量构造客户端（便捷方法）。

        自动加载项目根 .env 文件（若存在），环境变量优先级更高。
        """
        _load_env_file()
        return cls()

    @staticmethod
    def _extract_json_from_content(content: str) -> str:
        """从 LLM 响应内容中提取纯 JSON 字符串。

        支持三种格式：
            1. 纯 JSON（标准 Instruct 模型）：直接返回
            2. 含 ``</think>`` 标签的推理模型（DeepSeek-R1 / GLM-Z1 等）：
               提取标签后的内容
            3. 含 reasoning_content 字段时，content 可能已是纯 JSON

        参数：
            content  LLM 响应原始文本

        返回：
            提取后的 JSON 字符串（调用方负责 json.loads）

        异常：
            LLMError  无法提取合法 JSON
        """
        text = content.strip()

        # 情况 2：推理模型输出 </think> 标签
        # 格式：<think>思考过程...</think>真正的JSON
        # 或直接 ...</think>真正的JSON（无开标签）
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()

        # 此时 text 应为 JSON（可能被 ```json ... ``` 包裹）
        # 清理 markdown 代码块包裹
        if text.startswith("```"):
            # 移除首行 ```json 或 ```
            lines = text.split("\n", 1)
            if len(lines) > 1:
                text = lines[1]
            # 移除末尾 ```
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

        # 尝试提取第一个完整 JSON 对象（{ ... }）
        # 处理模型在 JSON 前后输出多余文本的情况
        if text and text[0] != "{":
            start = text.find("{")
            if start == -1:
                raise LLMError(
                    f"LLM 响应中未找到 JSON 对象: {text[:200]}"
                )
            # 从第一个 { 开始，找匹配的 }
            depth = 0
            end = -1
            in_string = False
            escape = False
            for i, ch in enumerate(text[start:], start):
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > start:
                text = text[start:end]

        return text

    def chat_json(self, messages: list[dict[str, str]]) -> str:
        """发送 chat completion 请求，强制 JSON 模式，返回响应文本。

        支持推理模型（DeepSeek-R1 / GLM-Z1 等）的 ``</think>`` 标签输出格式，
        自动提取思考过程后的纯 JSON 内容。

        参数：
            messages  OpenAI chat messages 格式列表

        返回：
            LLM 响应文本（应为合法 JSON 字符串，调用方负责 json.loads）

        异常：
            LLMTimeoutError     请求超时
            LLMRateLimitError   429 限流
            LLMClientError      4xx 客户端错误
            LLMServerError      5xx 服务端错误
        """
        # 动态计算 max_tokens：确保 input + output 不超过模型上下文窗口
        # Qwen2.5-7B=32768, DeepSeek-V4=64000+，用 env 配置或自动推算
        model_ctx = int(os.environ.get("LLM_MAX_CONTEXT", "32768"))
        # 估算输入 token 数（1 token ≈ 3.5 字符）
        input_chars = sum(len(m.get("content", "")) for m in messages)
        est_input_tokens = int(input_chars / 3.5) + 100  # 安全余量
        dynamic_max = min(self.max_tokens, model_ctx - est_input_tokens - 200)
        if dynamic_max < 2048:
            # 极端情况：输入已接近上下文上限，至少给 2048 输出
            dynamic_max = max(2048, model_ctx - est_input_tokens - 100)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": self.temperature,
            "max_tokens": dynamic_max,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                self._endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{self.timeout}s）: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMError(f"LLM 网络请求失败: {exc}") from exc

        # 非 2xx 状态码分类处理
        if response.status_code != 200:
            body = response.text
            if response.status_code == 429:
                raise LLMRateLimitError(
                    "LLM API 限流 (429)，请稍后重试",
                    status_code=429,
                    body=body,
                )
            if 400 <= response.status_code < 500:
                raise LLMClientError(
                    f"LLM 客户端错误 ({response.status_code}): {body[:500]}",
                    status_code=response.status_code,
                    body=body,
                )
            raise LLMServerError(
                f"LLM 服务端错误 ({response.status_code}): {body[:500]}",
                status_code=response.status_code,
                body=body,
            )

        # 解析响应
        try:
            data = response.json()
        except (ValueError, KeyError) as exc:
            raise LLMError(f"LLM 响应解析失败: {exc}\nbody={response.text[:500]}") from exc

        try:
            msg = data["choices"][0]["message"]
            content = msg.get("content", "")
            # 推理模型可能将思考过程放在 reasoning_content 字段
            # （OpenAI o1 / DeepSeek-R1 / GLM-Z1 等）
            reasoning = msg.get("reasoning_content", "")
        except (KeyError, IndexError) as exc:
            raise LLMError(
                f"LLM 响应结构异常，无法提取 content: {exc}\n"
                f"finish_reason={data.get('choices', [{}])[0].get('finish_reason', 'N/A')}"
            ) from exc

        # 记录 token 用量（API 返回的 usage 字段）
        usage = data.get("usage", {})
        self.last_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        finish_reason = data.get("choices", [{}])[0].get("finish_reason", "N/A")
        print(
            f"  [tokens] prompt={self.last_usage['prompt_tokens']} "
            f"completion={self.last_usage['completion_tokens']} "
            f"total={self.last_usage['total_tokens']} "
            f"finish_reason={finish_reason}"
        )
        if finish_reason == "length":
            print(f"  ⚠ 输出被截断（finish_reason=length），考虑增大 LLM_MAX_TOKENS（当前={self.max_tokens}）")

        if not content or not content.strip():
            # content 为空但 reasoning_content 有内容 → 思考过程耗尽 max_tokens
            if reasoning:
                raise LLMError(
                    f"LLM 返回空 content，但 reasoning_content 有 {len(reasoning)} 字符。"
                    f"可能思考过程耗尽 max_tokens={self.max_tokens}，"
                    f"请增大 LLM_MAX_TOKENS 或换非推理模型"
                )
            raise LLMError("LLM 返回空 content（可能 max_tokens 不足或被安全过滤）")

        # 提取纯 JSON（处理 </think> 标签 / markdown 代码块 / 多余文本）
        try:
            return self._extract_json_from_content(content)
        except LLMError:
            # 提取失败，返回原始 content 让上层 json.loads 报详细错误
            return content


# --------------------------------------------------------------------------- #
# 命令行入口
# --------------------------------------------------------------------------- #
def _main() -> int:
    """命令行入口：连通性测试 或 单篇 Evidence 抽取测试。

    用法：
        python -m pipeline.llm_client              # 连通性测试
        python -m pipeline.llm_client BT000001      # 单篇 Evidence 抽取（有缓存则直接读）
        python -m pipeline.llm_client BT000001 --force  # 强制重新抽取（覆盖缓存）

    缓存：抽取结果保存到 data/extracted/{RUN_VERSION}/{doc_id}_evidence.json，
    再次运行直接读取不调 LLM。换模型时改 .env 的 RUN_VERSION 即可隔离旧数据。

    前置条件：
        - 项目根 .env 文件配置了 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
        - 或环境变量已设置
    """
    # 尝试构造客户端
    try:
        client = LLMClient.from_env()
    except ValueError as exc:
        print(f"配置错误: {exc}")
        print("\n请在项目根目录创建 .env 文件：")
        print("  LLM_API_KEY=sk-你的密钥")
        print("  LLM_BASE_URL=https://api.openai.com")
        print("  LLM_MODEL=gpt-4o-mini")
        return 2

    run_version = get_run_version()
    print(f"endpoint : {client._endpoint}")
    print(f"model    : {client.model}")
    print(f"version  : {run_version}")

    # 无参数：连通性测试
    if len(sys.argv) < 2:
        print("正在发送测试请求...")
        try:
            raw = client.chat_json(
                [
                    {
                        "role": "user",
                        "content": '返回一个 JSON：{"status":"ok","message":"连接成功"}',
                    }
                ]
            )
            print(f"响应     : {raw[:200]}")
            print("连通性测试通过")
            return 0
        except LLMError as exc:
            print(f"连通性测试失败: {exc}")
            return 1

    # 有参数：旧三阶段 Evidence 抽取入口已迁移到 unified_extractor（方案 C）
    doc_id = sys.argv[1]
    print(f"旧三阶段抽取入口已废弃。请改用统一抽取器：")
    print(f"  python -m pipeline.unified_extractor {doc_id} --force")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
