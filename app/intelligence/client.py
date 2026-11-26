"""Paratera chat client. One place for timeout, thinking flag and JSON repair."""

import json
import re
from urllib.request import Request, urlopen

from .. import config


class ModelError(ValueError):
    """The model could not be reached or returned unusable text."""


def chat(model, messages, max_tokens, thinking=False, timeout=65):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "messages": messages}
    if not thinking:
        body["thinking"] = {"type": "disabled"}
    key = config.api_key()
    if not key:
        raise ModelError("未配置 Paratera 凭据，可先手填")
    request = Request(config.MODEL_ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            choice = json.load(response)["choices"][0]
    except (OSError, KeyError, IndexError, AttributeError, ValueError) as exc:
        raise ModelError("模型暂不可用，资料仍保留，可重试") from exc
    if choice.get("finish_reason") != "stop":
        raise ModelError("模型回复未完成，可重试或手填")
    content = choice.get("message", {}).get("content") or ""
    return content.strip()


def json_object(model, messages, max_tokens, timeout=70):
    raw = chat(model, messages, max_tokens, timeout=timeout)
    cleaned = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", raw)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ModelError("模型未返回 JSON 对象，可重试或手填")
    try:
        return json.loads(cleaned[start:end + 1])
    except ValueError as exc:
        raise ModelError("模型返回的 JSON 无法解析，可重试或手填") from exc
