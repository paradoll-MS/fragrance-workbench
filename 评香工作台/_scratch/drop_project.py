import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "workbench.sqlite3"
db = sqlite3.connect(DB)
db.execute("PRAGMA foreign_keys=OFF")
project = 2
slot_ids = [row[0] for row in db.execute(
    "SELECT s.id FROM slot s JOIN goal g ON g.id=s.goal_id JOIN subproject p ON p.id=g.subproject_id "
    "WHERE p.project_id=?", (project,))]
for slot_id in slot_ids:
    job_ids = [row[0] for row in db.execute("SELECT id FROM job WHERE slot_id=?", (slot_id,))]
    for job_id in job_ids:
        db.execute("DELETE FROM evaluation WHERE trial_id IN (SELECT id FROM trial WHERE job_id=?)", (job_id,))
        db.execute("DELETE FROM trial WHERE job_id=?", (job_id,))
    db.execute("DELETE FROM job WHERE slot_id=?", (slot_id,))
    check_ids = [row[0] for row in db.execute("SELECT id FROM check_set WHERE slot_id=?", (slot_id,))]
    for check_id in check_ids:
        db.execute("DELETE FROM requirement WHERE check_set_id=?", (check_id,))
    db.execute("DELETE FROM release_decision WHERE slot_id=?", (slot_id,))
    db.execute("DELETE FROM warehouse_record WHERE slot_id=?", (slot_id,))
    db.execute("DELETE FROM shipment WHERE slot_id=?", (slot_id,))
    db.execute("DELETE FROM task WHERE slot_id=?", (slot_id,))
    db.execute("DELETE FROM issue WHERE scope_type='slot' AND scope_id=?", (slot_id,))
    db.execute("DELETE FROM check_set WHERE slot_id=?", (slot_id,))
db.execute("DELETE FROM slot WHERE id IN (SELECT s.id FROM slot s JOIN goal g ON g.id=s.goal_id "
           "JOIN subproject p ON p.id=g.subproject_id WHERE p.project_id=?)", (project,))
db.execute("DELETE FROM goal WHERE subproject_id IN (SELECT id FROM subproject WHERE project_id=?)", (project,))
db.execute("DELETE FROM round WHERE subproject_id IN (SELECT id FROM subproject WHERE project_id=?)", (project,))
db.execute("DELETE FROM subproject WHERE project_id=?", (project,))
db.execute("DELETE FROM source WHERE project_id=?", (project,))
db.execute("DELETE FROM search_run WHERE project_id=?", (project,))
db.execute("DELETE FROM issue WHERE scope_type='project' AND scope_id=?", (project,))
db.execute("DELETE FROM audit WHERE entity_type='project' AND entity_id=?", (str(project),))
db.execute("DELETE FROM project WHERE id=?", (project,))
db.commit()
print("projects", db.execute("SELECT id, name, status FROM project").fetchall())
print("slots", db.execute("SELECT COUNT(*) FROM slot").fetchone())
