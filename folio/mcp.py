#!/usr/bin/env python3
"""Raw MCP client for Folio (book.tingting.vip/mcp). Usage: python3 mcp.py <tool> '<json-args>'"""
import json, os, sys, urllib.request, urllib.error

URL = "https://book.tingting.vip/mcp"
KEY = os.environ.get("BOOK_API_KEY", "")
if not KEY:
    raise SystemExit("BOOK_API_KEY empty")

_accept = "application/json, text/event-stream"
_id = 0

def post(session, payload):
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": _accept,
            "Authorization": f"Bearer {KEY}",
            **({"Mcp-Session-Id": session} if session else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            sid = r.headers.get("Mcp-Session-Id")
            ctype = r.headers.get("Content-Type", "")
            return r.status, sid, ctype, body
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Mcp-Session-Id") if e.headers else None, e.headers.get("Content-Type", "") if e.headers else "", e.read().decode()

def parse_body(ctype, body):
    if "text/event-stream" in ctype:
        for line in body.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    try:
                        return json.loads(data)
                    except json.JSONDecodeError:
                        continue
        return None
    if body.strip():
        return json.loads(body)
    return None

def init():
    global _sid
    payload = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "folio-rewrite", "version": "1.0"},
    }}
    status, sid, ctype, body = post(None, payload)
    _sid = sid
    result = parse_body(ctype, body)
    post(_sid, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return status, result

def method(name, params):
    global _id
    _id += 1
    payload = {"jsonrpc": "2.0", "id": _id, "method": name, "params": params}
    status, _sid2, ctype, body = post(_sid, payload)
    data = parse_body(ctype, body)
    if status != 200:
        raise SystemExit(f"HTTP {status}: {body[:2000]}")
    return data

def call(name, args):
    return method("tools/call", {"name": name, "arguments": args})

if __name__ == "__main__":
    tool = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    st, initres = init()
    data = call(tool, args)
    if data and data.get("error"):
        print(json.dumps({"error": data["error"]}, ensure_ascii=False))
    else:
        print(json.dumps(data, ensure_ascii=False))
