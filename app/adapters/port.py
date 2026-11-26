"""外部门面：工作台只通过这个协议与中台交互。真实接口实现同一组方法即可替换模拟器。"""

from typing import Protocol


class PlatformPort(Protocol):
    def dispatch(self, db, task):
        """送出一条部门任务，返回外部任务号。同业务键重复调用不得产生第二条任务。"""
        ...

    def pending(self, db, department=None):
        """返回尚未回执的任务。"""
        ...

    def status(self, db, task):
        """查询外部任务状态：queued / sent / done / failed / cancelled。"""
        ...

    def cancel(self, db, task, reason=""):
        ...

    def receipt(self, db, task, passed, payload=None):
        """登记一次部门回执，返回 {event_id, task_id, passed, payload}。"""
        ...

    def quote(self, db, code, price=None):
        """读取或写入报价。price 为 None 时只读。"""
        ...

    def quotes(self, db):
        ...

    def inventory(self, db, fragrance_id, formula_version=""):
        """返回 {available, sample_id, note}。"""
        ...

    def reserve(self, db, fragrance_id, formula_version, quantity, unit):
        """预留实物样，返回 {ok, sample_id, note}。"""
        ...

    def default_result(self, db, department, result=None):
        """读取或设置部门新任务的默认回执，None 表示不默认。"""
        ...
