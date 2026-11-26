import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:18762/api/projects/7/llm-calls", timeout=30) as r:
    data = json.loads(r.read().decode())
call = data["calls"][0]
with urllib.request.urlopen(f"http://127.0.0.1:18762/api/llm-calls/{call['id']}", timeout=30) as r:
    detail = json.loads(r.read().decode())
print(call["purpose"], call["status"], detail["request"]["messages"][0]["role"], len(detail["response"]))
print(detail["request"]["messages"][0]["content"][:80])
