from app.assets.catalog import Catalog
c = Catalog()
print("rules", len(c.llm_rules), "guidance", len(c.c_guidance), "leaves", sum(1 for t in c.terms.values() if t.get("level")=="C" and t.get("node_type")=="leaf"))
print("sample", c.c_guidance.get("C_574", "")[:60])
