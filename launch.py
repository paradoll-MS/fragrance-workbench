import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent
ADDRESS = "127.0.0.1"
PORT = 18761
URL = f"http://{ADDRESS}:{PORT}"
LOG = ROOT / "data" / "startup.log"


def service_ready():
    try:
        with urlopen(URL + "/api/health", timeout=0.7) as response:
            return json.load(response) == {"service": "fragrance-workbench", "ready": True}
    except (OSError, ValueError):
        return False


def start_service():
    if service_ready():
        return
    try:
        with socket.create_connection((ADDRESS, PORT), timeout=0.5):
            raise SystemExit(f"Port {PORT} is in use by another service.")
    except OSError:
        pass

    LOG.parent.mkdir(parents=True, exist_ok=True)
    options = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    with LOG.open("ab") as log:
        child = subprocess.Popen([sys.executable, "-u", str(ROOT / "server.py")],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 **options)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if service_ready():
            return
        if child.poll() is not None:
            break
        time.sleep(0.18)
    raise SystemExit(f"Workbench did not start. See {LOG}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    start_service()
    print(URL + "/projects")
    print(URL + "/mock-platform")
    if not args.no_browser:
        webbrowser.open(URL + "/projects")
