# jt/nodes.py
import json
import urllib.request
from pathlib import Path
from typing import Optional

NODES_FILE = Path.home() / '.config' / 'jt' / 'nodes.json'
DEFAULT_PORT = 6248


def load_nodes() -> list[dict]:
    try:
        return json.loads(NODES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def fetch_remote_state(node: dict, timeout: int = 3) -> Optional[dict]:
    url = f"http://{node['ip']}:{node.get('port', DEFAULT_PORT)}/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None
