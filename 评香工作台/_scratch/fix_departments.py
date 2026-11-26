import pathlib

path = pathlib.Path(__file__).resolve().parents[1] / "app" / "workflow" / "service.py"
text = path.read_text(encoding="utf-8")
original = text
text = text.replace('"analysis", "duplicate",', '"analysis", "analysis",')
text = text.replace('"perfumery", strategy,', '"perfumery", "perfumery",')
text = text.replace('"perfumery", "duplicate",', '"perfumery", "perfumery",')
text = text.replace('"perfumery", state["job"]["dev_type"],', '"perfumery", "perfumery",')
path.write_text(text, encoding="utf-8")
print("changed", text != original)
