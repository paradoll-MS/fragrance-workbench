"""Paths, service settings and model endpoints."""

import json
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = APP_ROOT.parent
RESOURCES = APP_ROOT / "resources"
CASES = APP_ROOT / "research" / "cases"
DATA = APP_ROOT / "data"
FRONTEND = APP_ROOT / "frontend"
MOCK_PLATFORM = APP_ROOT / "mock_platform"
DOCS = APP_ROOT / "docs"
DATABASE = DATA / "workbench.sqlite3"

HOST = "127.0.0.1"
PORT = 18761
SERVICE = "fragrance-workbench"
VERSION = "0.2.0"
DEBUG = os.environ.get("WORKBENCH_DEBUG") == "1"

MAX_UPLOAD = 30 * 1024 * 1024
MAX_REQUEST = 42 * 1024 * 1024
MAX_TEXT = 6000
SEED_TOTAL_LIMIT = 100_000

REVIEW_RULES = RESOURCES / "审查" / "香精审查规则_轻量版.json"
ABC_ROOT = RESOURCES / "ABC"
SCORING = APP_ROOT / "scoring.json"

PARSE_MODEL = os.environ.get("PARATERA_PARSE_MODEL", "DeepSeek-V4.1-Flash")
TARGETING_MODEL = os.environ.get("PARATERA_TARGETING_MODEL", "DeepSeek-V4-Flash-0731")
VISION_MODEL = os.environ.get("PARATERA_VISION_MODEL", "DeepSeek-V4-Flash-Vision-Exp")
MODEL_ENDPOINT = "https://llmapi.paratera.com/chat/completions"


def api_key():
    value = os.environ.get("PARATERA_API_KEY")
    if value:
        return value
    local = WORKSPACE / "API密钥配置" / "paratera密钥.txt"
    if local.exists():
        import re

        found = re.search(r"\bsk[-_][\w-]{16,}\b", local.read_text(encoding="utf-8-sig"))
        if found:
            return found.group()
    return ""


def scoring():
    return json.loads(SCORING.read_text(encoding="utf-8"))


def resource_dir(name):
    current = RESOURCES / name
    return current if current.exists() else WORKSPACE / name
