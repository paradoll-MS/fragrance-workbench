from app import config
from app.workflow.service import Workbench
db = config.DATA.parent / "_scratch" / "pdf-case.sqlite3"
wb = Workbench(database=db)
with wb.store.connect() as conn:
    print([d[1] for d in conn.execute("PRAGMA table_info(check_set)")])
    print([d[1] for d in conn.execute("PRAGMA table_info(slot)")])
    slot = conn.execute("SELECT * FROM slot WHERE id=1").fetchone()
    print(dict(slot).keys())
    for r in conn.execute("SELECT * FROM check_set ORDER BY id DESC LIMIT 2"):
        print(dict(r))
