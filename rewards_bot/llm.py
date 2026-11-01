from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from .config import AdvancedConfig


class LLMError(RuntimeError):
    """大模型接口调用失败或返回格式不合法。"""


class LLMClient:
    """OpenAI 兼容 Chat Completions 客户端，默认用于 DeepSeek。"""

    def __init__(
        self,
        cfg: AdvancedConfig,
        max_tokens: int = 1000,
    ) -> None:
        if not cfg.api_key:
            raise LLMError(
                "进阶模式未配置 API Key。请在 config.toml 的 [advanced].api_key 填写，"
                "或设置环境变量 DEEPSEEK_API_KEY。"
            )
        self.cfg = cfg
        self.log = logging.getLogger("rewards_bot.llm")
        self.max_tokens = max(64, int(max_tokens))
        self.last_usage: dict[str, Any] = {}
        self._http = requests.Session()
        self._http.headers.update(
            {
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        base = cfg.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            self.endpoint = base
        else:
            self.endpoint = f"{base}/chat/completions"
        if cfg.vision and not cfg.vision_supported:
            self.log.warning(
                "DeepSeek 官方 API 不接收图片，截图将只保存在本地用于排查；"
                "本轮使用文字化的元素索引。"
            )

    def complete(
        self,
        messages: list[dict[str, Any]],
        screenshot_path: Path | None = None,
    ) -> str:
        outgoing = self._with_screenshot(messages, screenshot_path)
        self.last_usage = {}
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": outgoing,
            "temperature": self.cfg.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._http.post(
                    self.endpoint,
                    json=payload,
                    timeout=(20, self.cfg.timeout_seconds),
                )
                if response.status_code == 400 and "response_format" in response.text.lower():
                    self.log.warning("接口不支持 response_format，改为普通补全后重试。")
                    payload.pop("response_format", None)
                    response = self._http.post(
                        self.endpoint,
                        json=payload,
                        timeout=(20, self.cfg.timeout_seconds),
                    )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise LLMError(
                        f"接口暂时不可用：HTTP {response.status_code} {response.text[:300]}"
                    )
                if response.status_code >= 400:
                    raise LLMError(
                        f"接口返回 HTTP {response.status_code}：{response.text[:500]}"
                    )
                data = response.json()
                usage = data.get("usage") or {}
                if usage:
                    self.last_usage = dict(usage)
                    self.log.debug(
                        "token 用量：prompt=%s completion=%s total=%s",
                        usage.get("prompt_tokens"),
                        usage.get("completion_tokens"),
                        usage.get("total_tokens"),
                    )
                choices = data.get("choices") or []
                if not choices:
                    raise LLMError(f"接口响应中没有 choices：{str(data)[:300]}")
                content = choices[0].get("message", {}).get("content", "")
                if not isinstance(content, str) or not content.strip():
                    raise LLMError("模型返回了空内容。")
                return content
            except (requests.RequestException, LLMError) as exc:
                last_error = exc
                if attempt >= 3:
                    break
                delay = 1.5 * (2 ** (attempt - 1))
                self.log.warning("大模型调用失败（第 %s/3 次），%.1f 秒后重试：%s", attempt, delay, exc)
                time.sleep(delay)
        raise LLMError(f"大模型调用最终失败：{last_error}")

    def _with_screenshot(
        self,
        messages: list[dict[str, Any]],
        screenshot_path: Path | None,
    ) -> list[dict[str, Any]]:
        if screenshot_path is None or not screenshot_path.exists() or not self.cfg.vision_supported:
            return messages
        try:
            encoded = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
            system_messages = [m for m in messages if m.get("role") == "system"]
            other_messages = [m for m in messages if m.get("role") != "system"]
            user_content: list[dict[str, Any]] = [
                {"type": "text", "text": "\n\n".join(str(m.get("content", "")) for m in other_messages)}
            ]
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                }
            )
            result: list[dict[str, Any]] = []
            result.extend(system_messages)
            result.append({"role": "user", "content": user_content})
            return result
        except Exception as exc:
            self.log.warning("无法附加截图，将只发送文本：%s", exc)
            return messages

    @staticmethod
    def parse_json_object(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise LLMError(f"模型输出不是 JSON：{content[:300]}")
            try:
                value = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMError(f"模型输出 JSON 解析失败：{content[:300]}") from exc
        if not isinstance(value, dict):
            raise LLMError("模型输出的 JSON 顶层必须是对象。")
        return value
