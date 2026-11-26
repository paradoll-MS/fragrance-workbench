"""本地模拟中台：实现 PlatformPort，把外部世界缩成一张任务表与两条模拟规则。"""

from ..domain.normalize import clean, price_value
from ..store.db import dumps, one, now


class MockPlatform:
    name = "mock"
    env = "mock"

    def __init__(self):
        self._sequence = 0

    def _next(self, prefix):
        self._sequence += 1
        return f"{prefix}-{now()[:10].replace('-', '')}-{self._sequence:04d}"

    def dispatch(self, db, task):
        external = self._next("MOCK-T" + task["department"].upper()[:3])
        default = self.default_result(db, task["department"])
        status = "done" if default is not None else "sent"
        note = "" if default is None else ("默认回执：通过" if default else "默认回执：退回")
        db.execute("UPDATE task SET status=?, external_id=?, note=?, updated_at=? WHERE id=?",
                   (status, external, note, now(), task["id"]))
        if default is not None:
            db.execute("INSERT INTO audit(command,entity_type,entity_id,action,payload,revision,actor,created_at)"
                       " VALUES('receipt','task',?,?,?,0,'mock',?)",
                       (str(task["id"]), "mock_default", dumps({"passed": bool(default)}), now()))
        return external

    def pending(self, db, department=None):
        sql = "SELECT * FROM task WHERE status='sent'"
        params = ()
        if department:
            sql += " AND department=?"
            params = (department,)
        return db.execute(sql + " ORDER BY id", params).fetchall()

    def status(self, db, task):
        return one(db, "SELECT status FROM task WHERE id=?", (task["id"],), "missing")

    def cancel(self, db, task, reason=""):
        db.execute("UPDATE task SET status='cancelled', note=?, updated_at=? WHERE id=?",
                   (clean(reason, 300), now(), task["id"]))

    def receipt(self, db, task, passed, payload=None):
        payload = payload or {}
        db.execute("UPDATE task SET status=?, note=?, updated_at=? WHERE id=?",
                   ("done" if passed else "failed", clean(payload.get("note"), 300), now(), task["id"]))
        return {"event_id": self._next("MOCK-EVT"), "task_id": task["id"],
                "passed": bool(passed), "payload": payload}

    def quote(self, db, code, price=None):
        if price is None:
            return one(db, "SELECT price FROM quote WHERE code=?", (code,))
        if price_value(price) is None:
            db.execute("DELETE FROM quote WHERE code=?", (code,))
            return None
        db.execute("INSERT INTO quote(code,price,updated_at) VALUES(?,?,?) "
                   "ON CONFLICT(code) DO UPDATE SET price=excluded.price, updated_at=excluded.updated_at",
                   (code, str(price_value(price)), now()))
        return str(price_value(price))

    def quotes(self, db):
        return {item["code"]: item["price"] for item in db.execute("SELECT code, price FROM quote")}

    def inventory(self, db, fragrance_id, formula_version=""):
        if not fragrance_id:
            return {"available": False, "sample_id": "", "note": "缺少香精编号"}
        return {"available": True, "sample_id": self._next("MOCK-SAMPLE"), "note": "模拟有货"}

    def reserve(self, db, fragrance_id, formula_version, quantity, unit):
        stock = self.inventory(db, fragrance_id, formula_version)
        if not stock["available"]:
            return {"ok": False, "sample_id": "", "note": stock["note"]}
        return {"ok": True, "sample_id": stock["sample_id"],
                "note": f"{clean(quantity)} {clean(unit)}".strip()}

    def default_result(self, db, department, result=None):
        if result is None and department is None:
            return {item["department"]: item["result"] for item in db.execute("SELECT * FROM mock_default")}
        if result is None and department:
            return one(db, "SELECT result FROM mock_default WHERE department=?", (department,))
        if result == "":
            result = None
        if result is None:
            db.execute("DELETE FROM mock_default WHERE department=?", (department,))
            return None
        db.execute("INSERT INTO mock_default(department,result) VALUES(?,?) "
                   "ON CONFLICT(department) DO UPDATE SET result=excluded.result",
                   (department, 1 if result else 0))
        return 1 if result else 0
