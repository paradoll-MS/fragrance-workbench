from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = APP_ROOT.parent
RESOURCES = WORKSPACE / "resources-资源"
CASES = WORKSPACE / "cases-案例"


def resource_path(name):
    current = RESOURCES / name
    return current if current.exists() else WORKSPACE / name
