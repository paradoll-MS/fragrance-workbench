"""Retained V2 HTTP/read helpers. Generation and task behavior live in V3 modules."""
from __future__ import annotations
import json
import re
import mimetypes
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from . import db
ROOT = Path(__file__).resolve().parents[1]

def project_or_404(con,pid):
    p = db.one(con,'select * from projects where id=?',(pid,))
    if not p: raise KeyError('项目不存在')
    return p

class Handler(BaseHTTPRequestHandler):
    def api(self,method,path,q):
        if method=='GET' and path=='/api/library/search': return self.library_search(q)
        if method=='GET' and path=='/api/categories':
            con=db.connect(); rows=db.rows(con,'select * from category_map order by k_code');con.close()
            return self._ok({'items':rows})
        if method=='GET' and path=='/api/library/meta':
            con=db.connect(); count=db.one(con,'select count(*) n from library_items')['n'];con.close()
            return self._ok({'formulas':count})
        if method=='POST' and path=='/api/category/resolve':
            b=self._json_body(); con=db.connect(); row=self._resolve_category(con,b.get('l3'));con.close()
            return self._ok({'item':row})
        return self._err('接口不存在',404)
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _err(self, msg, code=400):
        self._send(code, {"ok": False, "error": str(msg)})

    def _ok(self, data=None):
        self._send(200, {"ok": True, **(data or {})})

    def do_OPTIONS(self):
        self._send(204, b"", headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*"})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")

    def library_search(self, q):
        from . import identity
        text = (q.get("q") or "").strip()
        con = db.connect()
        items,total=identity.Index(con).search(text,brand=q.get('brand',''),product=q.get('product',''));con.close()
        self._ok({"items":items,"total":total})

    def projects_list(self):
        con = db.connect()
        rows = db.rows(con, "select * from projects order by updated_at desc")
        con.close(); self._ok({"items": rows})

    @staticmethod
    def _drop_subproject(con, sid):
        con.execute("delete from recommendation_items where recommendation_id in (select id from recommendations where subproject_id=?)", (sid,))
        for t in ("recommendations", "endpoint_checks", "department_tasks", "external_samples"):
            con.execute(f"delete from {t} where subproject_id=?", (sid,))
        con.execute("delete from briefs where subproject_id=?", (sid,))
        con.execute("delete from subprojects where id=?", (sid,))

    def artifact_delete(self, aid):
        con = db.connect(); a = db.one(con, "select * from artifacts where id=?", (aid,))
        if not a: return self._err("not found", 404)
        if a.get("stored_name"):
            try: (db.UPLOADS / a["stored_name"]).unlink(missing_ok=True)
            except Exception: pass
        con.execute("delete from artifacts where id=?", (aid,))
        con.commit(); con.close(); self._ok({"deleted": aid})

    @staticmethod
    def fetch_link(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read(800000).decode("utf-8", "replace")
            raw = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
            raw = re.sub(r"(?s)<[^>]+>", " ", raw)
            raw = re.sub(r"\s+", " ", raw)
            return raw.strip()[:200000]
        except Exception:
            return ""

    def artifact_get(self, aid):
        con = db.connect(); a = db.one(con, "select * from artifacts where id=?", (aid,)); con.close()
        if not a:
            return self._err("not found", 404)
        a["file_url"] = f"/api/artifacts/{aid}/file"
        self._ok({"artifact": a})

    def artifact_file(self, aid):
        con = db.connect(); a = db.one(con, "select * from artifacts where id=?", (aid,)); con.close()
        if not a or not a.get("stored_name"):
            return self._err("file not found", 404)
        f = db.UPLOADS / a["stored_name"]
        if not f.exists():
            return self._err("file not found", 404)
        self._send(200, f.read_bytes(), a.get("mime") or "application/octet-stream",
                   {"Content-Disposition": "inline"})

    def artifact_classify(self, aid):
        con = db.connect(); a = db.one(con, "select * from artifacts where id=?", (aid,)); con.close()
        if not a:
            return self._err("not found", 404)
        try:
            d = self._auto_classify(aid, a.get("project_id") or "")
        except Exception as e:
            return self._err(str(e), 502)
        self._ok({"result": d})

    @staticmethod
    def _norm_defaults(norm_class, markets):
        try:
            data = json.loads((ROOT / "data" / "规范类默认指标.json").read_text(encoding="utf-8"))
        except Exception:
            return {}
        d = (data.get("norm_class_defaults") or {}).get(norm_class or "", {})
        if not d:
            return {}
        reg = d.get("regulatory_by_region") or {}
        if markets:
            reg = {k: v for k, v in reg.items() if k in markets}
        return {
            "norm_class": norm_class,
            "ifra": d.get("ifra"), "allergen": d.get("allergen"), "sds_coa": d.get("sds_coa"),
            "performance_codes": d.get("performance_codes") or [],
            "stability_codes": d.get("stability_codes") or [],
            "regulatory_by_region": reg,
        }

    @staticmethod
    def _resolve_category(con, q):
        q = (q or "").strip()
        if not q:
            return None
        rows = db.rows(con, "select * from category_map")
        for r in rows:
            if q == r["level3"] or q in (json.loads(r["aliases_json"] or "[]")):
                return r
        # “儿童洗发水”这类带修饰词的 L3：取包含关系最长匹配
        hits = [r for r in rows if r["level3"] and (r["level3"] in q or q in r["level3"])]
        if hits:
            return max(hits, key=lambda r: len(r["level3"]))
        return None

    def usage(self, pid):
        con = db.connect(); project_or_404(con, pid)
        totals = db.one(con, """select count(*) calls, coalesce(sum(total_tokens),0) tokens,
                                coalesce(sum(cost),0) cost, coalesce(sum(elapsed),0) elapsed
                                from llm_calls where project_id=?""", (pid,))
        recent = db.rows(con, "select node,provider,model,prompt_tokens,completion_tokens,total_tokens,cost,elapsed,created_at,details_json from llm_calls where project_id=? order by created_at desc limit 20", (pid,))
        con.close(); self._ok({"totals": totals, "recent": recent})
