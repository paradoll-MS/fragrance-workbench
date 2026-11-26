"""HTTP surface: parse a request, call one command, return JSON. No business rules here."""

import base64
import json
import mimetypes
import posixpath
import re
import traceback
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    raise TypeError(f"无法序列化 {type(value).__name__}")

from .. import config
from ..domain import enums
from ..workflow import views
from ..workflow.service import Workbench

ROUTES = []


def route(method, pattern):
    def wrap(function):
        ROUTES.append((method, re.compile("^" + pattern + "$"), function))
        return function

    return wrap


class Body:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]


def _sources(workbench, project_id, body):
    name = (body.get("name") or "资料").strip()
    if body.get("text"):
        return workbench.add_source(project_id, name, text=body["text"])
    payload = body.get("base64") or ""
    if not payload:
        raise ValueError("没有收到文件内容")
    raw = base64.b64decode(payload.split(",")[-1])
    if len(raw) > config.MAX_UPLOAD:
        raise ValueError("文件超过 30MB，请拆分后上传")
    return workbench.add_source(project_id, name, raw=raw, vision=bool(body.get("vision")))


@route("GET", "/api/health")
def health(workbench, body, match):
    return {"ok": True, "service": config.SERVICE, "version": config.VERSION,
            "schema": 1, "rules": workbench.rules.version,
            "scoring": workbench.config.get("version", ""), "platform": workbench.platform.name}


@route("GET", "/api/bootstrap")
def bootstrap(workbench, body, match):
    return views.bootstrap(workbench)


@route("GET", "/api/projects")
def projects(workbench, body, match):
    return views.project_list(workbench)


@route("POST", "/api/projects")
def create_project(workbench, body, match):
    project_id = workbench.create_project(body.get("name"), body.get("kind", "customer"),
                                          body.get("customer", ""), body.get("code", ""))
    return {"project_id": project_id}


@route("PATCH", "/api/projects/(\\d+)")
def rename_project(workbench, body, match):
    workbench.rename_project(int(match.group(1)), body.get("name", ""), body.get("customer", ""))
    return {"ok": True}


@route("GET", "/api/projects/(\\d+)")
def project_view(workbench, body, match):
    return views.project_view(workbench, int(match.group(1)))


@route("POST", "/api/projects/(\\d+)/sources")
def add_source(workbench, body, match):
    source_id = _sources(workbench, int(match.group(1)), body)
    return {"source_id": source_id}


@route("POST", "/api/projects/(\\d+)/analyze")
def analyze(workbench, body, match):
    draft_id, result, meta = workbench.analyze(int(match.group(1)), body.get("source_ids"), body.get("model"))
    return {"draft_id": draft_id, "draft": result, "meta": meta}


@route("POST", "/api/projects/(\\d+)/draft")
def manual_draft(workbench, body, match):
    draft_id, result = workbench.manual_draft(int(match.group(1)), body.get("directions") or [])
    return {"draft_id": draft_id, "draft": result}


@route("POST", "/api/projects/(\\d+)/draft/(\\d+)/confirm")
def confirm(workbench, body, match):
    committed = workbench.confirm_draft(int(match.group(1)), int(match.group(2)),
                                        body.get("edits"), body.get("kind", "customer"))
    return {"committed": committed.get("directions", committed) if isinstance(committed, dict) else committed}


@route("POST", "/api/projects/(\\d+)/goals/(\\d+)/plan")
def plan(workbench, body, match):
    return workbench.plan(int(match.group(1)), int(match.group(2)), body.get("strategy"),
                          body.get("payload") or {})


@route("POST", "/api/projects/(\\d+)/goals/(\\d+)/reroute")
def reroute(workbench, body, match):
    return workbench.reroute(int(match.group(1)), int(match.group(2)), body.get("entry"))


@route("POST", "/api/projects/(\\d+)/slots/(\\d+)/advance")
def advance(workbench, body, match):
    return workbench.advance(int(match.group(1)), int(match.group(2)), body.get("action"),
                             body.get("payload") or {}, body.get("revision"))


@route("POST", "/api/search")
def search(workbench, body, match):
    query = body.get("query")
    if isinstance(query, str):
        query = {"text": query}
    return workbench.search(query or {}, body.get("page", 1), body.get("project_id"),
                            body.get("limit", 30), body.get("goal_id"))


@route("POST", "/api/target")
def target(workbench, body, match):
    return workbench.target(body.get("text", ""), body.get("mode", "recommend_simple"),
                            [item["id"] for item in workbench.rules.category_options()])


@route("POST", "/api/asset")
def edit_asset(workbench, body, match):
    return workbench.edit_asset(body.data)


@route("GET", "/api/platform")
def platform(workbench, body, match):
    return views.platform_view(workbench)


@route("POST", "/api/platform/receipt")
def receipt(workbench, body, match):
    return workbench.apply_receipt(int(body.get("task_id")), bool(body.get("passed")),
                                   body.get("payload") or {})


@route("POST", "/api/platform/default")
def platform_default(workbench, body, match):
    with workbench.store.transaction() as db:
        result = workbench.platform.default_result(db, body.get("department"), body.get("result"))
    return {"result": result}


@route("POST", "/api/platform/quote")
def platform_quote(workbench, body, match):
    with workbench.store.transaction() as db:
        price = workbench.platform.quote(db, body.get("code"), body.get("price"))
    return {"price": price}


class Handler(BaseHTTPRequestHandler):
    workbench = None
    server_version = "FragranceWorkbench/" + config.VERSION

    def log_message(self, fmt, *args):
        if config.DEBUG:
            print("%s - %s" % (self.address_string(), fmt % args))

    def _send(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        if path in ("/mock.html", "/mock"):
            root, safe = config.MOCK_PLATFORM, "index.html"
        elif path == "/mock.js":
            root, safe = config.MOCK_PLATFORM, "app.js"
        else:
            root = config.FRONTEND
            safe = posixpath.normpath(path).lstrip("/")
        target = (root / safe).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            return self._send(404, {"error": "页面不存在"})
        if not target.is_file():
            return self._send(404, {"error": "页面不存在"})
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript", "application/json"):
            mime += "; charset=utf-8"
        self._send(200, target.read_bytes(), mime)

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        if length > config.MAX_REQUEST:
            return self._send(413, {"error": "请求过大"})
        raw = self.rfile.read(length) if length else b""
        body = Body()
        if raw:
            try:
                body = Body(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._send(400, {"error": "请求体不是合法 JSON"})
        for route_method, pattern, function in ROUTES:
            if route_method != method:
                continue
            match = pattern.match(path)
            if not match:
                continue
            try:
                result = function(self.workbench, body, match)
            except ValueError as error:
                return self._send(400, {"error": str(error)})
            except Exception as error:  # noqa: BLE001 - the UI must always get JSON
                traceback.print_exc()
                return self._send(500, {"error": "服务内部错误：" + type(error).__name__})
            return self._send(200, result)
        if path.startswith("/api/"):
            return self._send(404, {"error": "接口不存在"})
        if method in ("GET", "HEAD"):
            return self._static(path)
        return self._send(405, {"error": "不支持的请求方法"})

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")


def serve(port=None, host=None):
    Handler.workbench = Workbench()
    server = ThreadingHTTPServer((host or config.HOST, port or config.PORT), Handler)
    print(f"{config.SERVICE} {config.VERSION} → http://{server.server_address[0]}:{server.server_address[1]}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
