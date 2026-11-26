"""Paratera chat client. One place for timeout, thinking flag and JSON repair.

`trace` is an optional dict the caller passes in. It is filled with the exact
request body, raw response, status, error and duration so the workbench can show
every model call instead of only its parsed result. The API key never enters it.
"""

import json
import re
from time import perf_counter
from urllib.request import Request, urlopen

from .. import config


class ModelError(ValueError):
    """The model could not be reached or returned unusable text."""


def _finish(trace, started, **values):
    if trace is None:
        return
    trace.update(values)
    trace["seconds"] = round(perf_counter() - started, 2)


def chat(model, messages, max_tokens, thinking=False, timeout=65, trace=None):
    started = perf_counter()
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "messages": messages}
    if not thinking:
        body["thinking"] = {"type": "disabled"}
    if trace is not None:
        trace.update({"model": model, "request": body, "response": "", "error": "",
                      "status": "pending", "seconds": 0})
    key = config.api_key()
    if not key:
        _finish(trace, started, status="error", error="未配置 Paratera 凭据，可先手填")
        raise ModelError("未配置 Paratera 凭据，可先手填")
    request = Request(config.MODEL_ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            choice = json.load(response)["choices"][0]
    except (OSError, KeyError, IndexError, AttributeError, ValueError) as exc:
        _finish(trace, started, status="error", error="模型暂不可用，资料仍保留，可重试")
        raise ModelError("模型暂不可用，资料仍保留，可重试") from exc
    if choice.get("finish_reason") != "stop":
        _finish(trace, started, status="incomplete", error="模型回复未完成，可重试或手填")
        raise ModelError("模型回复未完成，可重试或手填")
    content = choice.get("message", {}).get("content") or ""
    _finish(trace, started, status="ok", response=content.strip())
    return content.strip()


def json_object(model, messages, max_tokens, timeout=70, trace=None):
    try:
        raw = chat(model, messages, max_tokens, timeout=timeout, trace=trace)
    except ModelError:
        raise
    cleaned = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", raw)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        if trace is not None:
            trace.update(status="invalid_json", error="模型未返回 JSON 对象，可重试或手填")
        raise ModelError("模型未返回 JSON 对象，可重试或手填")
    try:
        return json.loads(cleaned[start:end + 1])
    except ValueError as exc:
        if trace is not None:
            trace.update(status="invalid_json", error="模型返回的 JSON 无法解析，可重试或手填")
        raise ModelError("模型返回的 JSON 无法解析，可重试或手填") from exc
