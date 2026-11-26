from __future__ import annotations
from . import prompt_store

import base64
import json
import os
import time
from contextvars import ContextVar
import urllib.error
import urllib.request
from pathlib import Path

from . import db

DEFAULTS = {
    "providers": {
        "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-pro", "api_key": ""},
        "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.8-max", "api_key": ""},
    }
}
ENV = {"deepseek": "DEEPSEEK_API_KEY", "qwen": "QWEN_API_KEY"}
_CTX = ContextVar('llm_context', default={"project_id": "", "node": ""})


def begin(project_id: str, node: str):
    _CTX.set({"project_id": project_id or "", "node": node or ""})


class ModelOutputLimit(RuntimeError):
    def __init__(self,details,partial):
        self.details={**details,'partial_content':partial}
        super().__init__(f"模型响应被长度上限截断（总生成{details.get('completion_tokens',0)} tokens；正文{details.get('content_characters',0)}字符）；旧结果保留，未写入不完整结果")


def response_details(data,request=None):
    request=request or {};usage=data.get('usage') or {};choice=(data.get('choices') or [{}])[0];message=choice.get('message') or {}
    return {'finish_reason':choice.get('finish_reason'),'requested_max_tokens':request.get('max_tokens'),
            'requested_thinking':request.get('thinking',{}).get('type') if 'thinking' in request else request.get('enable_thinking'),
            'requested_reasoning_effort':request.get('reasoning_effort'),
            'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':usage.get('completion_tokens'),
            'reasoning_tokens':(usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
            'content_characters':len(message.get('content') or ''),'reasoning_characters':len(message.get('reasoning_content') or '')}


def _record(provider, model, data, started, request=None):
    ctx = _CTX.get()
    pid = ctx.get("project_id")
    if not pid:
        return
    usage = (data or {}).get("usage") or {}
    pin = int(usage.get("prompt_tokens") or 0)
    pout = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or pin + pout)
    # 估算：输入 0.5 元/百万 token，输出 2 元/百万 token；仅用于成本可见，不是账单
    cost = pin * 0.5 / 1_000_000 + pout * 2.0 / 1_000_000
    try:
        con = db.connect()
        con.execute("insert into llm_calls(id,project_id,node,provider,model,prompt_tokens,completion_tokens,total_tokens,cost,elapsed,created_at,details_json) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (db.uid("llm_"), pid, ctx.get("node") or "", provider, model,
                     pin, pout, total, cost, round(time.time() - started, 2), db.now(),db.js(response_details(data,request))))
        con.commit(); con.close()
    except Exception:
        pass


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def config():
    cfg = json.loads(json.dumps(DEFAULTS))
    if db.CONFIG_PATH.exists():
        try:
            cfg = _merge(cfg, json.loads(db.CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    for name, env in ENV.items():
        if os.environ.get(env):
            cfg["providers"].setdefault(name, {})["api_key"] = os.environ[env]
    return cfg


def provider(name=None):
    cfg = config()["providers"]
    name = name or ("deepseek" if cfg.get("deepseek", {}).get("api_key") else "qwen")
    p = cfg.get(name) or {}
    if not p.get("api_key"):
        raise RuntimeError(f"{name} API key 未配置")
    return name, p


def chat(messages, model=None, provider_name=None, max_tokens=4000, temperature=0.2, json_mode=False, timeout=180, reasoning_effort=None, thinking=None):
    started = time.time()
    name, p = provider(provider_name)
    url = p["base_url"].rstrip("/") + "/chat/completions"
    body = {
        "model": model or p.get("model"),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if name == "qwen":
        # DashScope 兼容模式：抽取/映射任务关闭隐藏推理，避免输出预算被 thinking 吃掉
        body["enable_thinking"] = False
    elif name == 'deepseek':
        # Keep full-project reasoning; parsing/QA need extraction, not a hidden long reasoning pass.
        understanding = reasoning_effort is not None or _CTX.get().get('node') in ('understand_project_v3','understand_project_v3_coherence_repair')
        if thinking is not None: understanding=bool(thinking)
        body['thinking'] = {'type':'enabled' if understanding else 'disabled'}
        if understanding:
            body['reasoning_effort'] = reasoning_effort or p.get('reasoning_effort') or 'high'
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + p["api_key"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{name} HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
    _record(name, model or p.get("model"), data, started,body)
    choice = data['choices'][0]
    if choice.get('finish_reason') == 'length':
        raise ModelOutputLimit(response_details(data,body),choice.get('message',{}).get('content') or '')
    text = choice["message"].get("content") or ""
    if not text.strip():
        raise RuntimeError(f'{name} 模型返回空内容，本轮未自动换模型重跑')
    return text


def chat_json(messages, **kw):
    def parse(t):
        t = (t or "").strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[-1]
            if t.endswith("```"):
                t = t[:-3]
        # 容忍模型在 JSON 前后加少量说明
        if not t.startswith("{"):
            i, j = t.find("{"), t.rfind("}")
            if i >= 0 and j > i:
                t = t[i:j + 1]
        return json.loads(t)
    return parse(chat(messages, json_mode=True, **kw))


def _post(url, key, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def vision_describe(data: bytes, mime: str = "image/png", model="qwen3-vl-plus"):
    started = time.time()
    _, p = provider("qwen")
    b64 = base64.b64encode(data).decode("ascii")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt_store.system('vision')},
            {"type": "image_url", "image_url": {"url": f"data:{mime or 'image/png'};base64,{b64}"}},
        ]}],
        "stream": False, "max_tokens": 4000, "enable_thinking": False,
    }
    d = _post(p["base_url"].rstrip("/") + "/chat/completions", p["api_key"], body)
    _record("qwen", model, d, started,body)
    if (d.get('choices') or [{}])[0].get('finish_reason')=='length':
        raise RuntimeError('图片文字未转写完整，保留原件，请拆分图片后重试')
    return (d.get("choices") or [{}])[0].get("message", {}).get("content", "")


def asr_transcribe(data: bytes, mime: str = "audio/mpeg", model="qwen3-asr-flash"):
    started = time.time()
    _, p = provider("qwen")
    if len(data) > 7 * 1024 * 1024:
        raise RuntimeError("音频超过 7MB；请拆到每段 5 分钟以内，或上传会议纪要文字。")
    b64 = base64.b64encode(data).decode("ascii")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": f"data:{mime or 'audio/mpeg'};base64,{b64}"}}]}],
        "stream": False,
        "asr_options": {"enable_itn": False},
    }
    d = _post(p["base_url"].rstrip("/") + "/chat/completions", p["api_key"], body)
    _record("qwen", model, d, started,body)
    return (d.get("choices") or [{}])[0].get("message", {}).get("content", "")


def vision(path, prompt, model="qwen-vl-max"):
    _, p = provider("qwen")
    raw = Path(path).read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    url = p["base_url"].rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "max_tokens": 2000,
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + p["api_key"]},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"].get("content") or ""
