import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:18762/api/projects/7/llm-calls", timeout=20) as r:
    data = json.loads(r.read().decode())
print("calls", len(data["calls"]), data["calls"][0]["purpose"] if data["calls"] else "")
