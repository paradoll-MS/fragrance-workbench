from pathlib import Path
import subprocess
out=Path('fragrance-copilot-v3/data/verification/逐本');exe=Path('C:/Users/26519/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe')
for f in Path('案例/逐本').glob('*.pdf'):
 target=out/('meeting' if f.name.startswith('2026') else 'strategy');target.mkdir(exist_ok=True)
 subprocess.run([str(exe),'-scale-to','1300','-png',str(f),str(target/'page')],check=True)
 print(target, len(list(target.glob('*.png'))))
