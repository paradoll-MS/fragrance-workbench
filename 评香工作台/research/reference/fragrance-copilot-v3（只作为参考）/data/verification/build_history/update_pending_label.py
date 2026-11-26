from pathlib import Path
p=Path('fragrance-copilot-v3/web/app.js');s=p.read_text(encoding='utf-8-sig').replace("draft:'准备需求',analysis:","draft:'准备需求',awaiting_source_sync:'等待首轮样品编号同步',awaiting_base:'确认基准原样',analysis:");p.write_text(s,encoding='utf-8')
