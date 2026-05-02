# jt/nodes.py
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

NODES_FILE = Path.home() / '.config' / 'jt' / 'nodes.json'
DEFAULT_PORT = 6248
FETCH_TIMEOUT = 3


def load_nodes() -> list[dict]:
    try:
        result = json.loads(NODES_FILE.read_text())
        return result if isinstance(result, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def fetch_remote_state(node: dict, timeout: int = FETCH_TIMEOUT) -> Optional[dict]:
    ip = node.get('ip')
    if not ip:
        return None
    port = node.get('port') or DEFAULT_PORT
    try:
        url = f"http://{ip}:{int(port)}/status"
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — http only
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_remotes(nodes: list[dict], timeout: int = FETCH_TIMEOUT) -> list[tuple[dict, Optional[dict]]]:
    """Fetch each node's /status concurrently.

    Returns a list of (node, state_or_none) preserving the input order so the
    rendered output stays stable between calls.
    """
    if not nodes:
        return []
    with ThreadPoolExecutor(max_workers=min(len(nodes), 8)) as pool:
        results = list(pool.map(lambda n: (n, fetch_remote_state(n, timeout)), nodes))
    return results
