from app.assets.catalog import Catalog
c = Catalog()
print(list(c.c_guidance.items())[:2])
print("C574", c.terms.get("C_574"))
print([k for k in c.terms if c.terms[k].get("name")=="花香调"][:3])
