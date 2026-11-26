import json, sqlite3
conn = sqlite3.connect("data/workbench.sqlite3")
conn.row_factory = sqlite3.Row
for row in conn.execute("SELECT g.id, g.label, g.fields FROM goal g JOIN subproject s ON s.id=g.subproject_id WHERE s.project_id=4"):
    f = json.loads(row["fields"])
    print(row["id"], row["label"], "scent=", f.get("scent"), "scent_text=", f.get("scent_text"), "audience=", f.get("target_audience"), "app=", f.get("application_id"))
