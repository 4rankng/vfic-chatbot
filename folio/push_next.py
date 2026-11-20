#!/usr/bin/env python3
"""push_next.py — publish the working copy (next/) to the Folio wiki (book.tingting.vip).

Mirrors the guard used by the earlier rewrite pipeline: a page that shrinks by more
than 10% is skipped, because a large shrink usually means a section was dropped by
accident rather than rewritten.

Usage:
  python3 push_next.py --dry                 # report only, no writes
  python3 push_next.py spec-4 lcl            # push only these page keys
  python3 push_next.py                       # push every page in next/
"""
import json
import os
import sys

import mcp

ROOT = os.path.dirname(os.path.abspath(__file__))
SHRINK_GUARD = 0.90  # keep at least 90% of the currently published length


def load_pages():
    with open(os.path.join(ROOT, "pages.json")) as f:
        return json.load(f)


def read_live(pid):
    d = mcp.call("read_page", {"id": pid})
    content = d.get("result", {}).get("content", [])
    if not content:
        raise SystemExit(f"read_page {pid}: empty content")
    return json.loads(content[0]["text"])["markdown"]


def push(key, pages, dry):
    path = os.path.join(ROOT, "next", f"{key}.md")
    if not os.path.exists(path):
        print(f"{key}: no next/{key}.md — skip", flush=True)
        return False
    pid = pages.get(key)
    if not pid:
        print(f"{key}: no page id in pages.json — skip", flush=True)
        return False

    with open(path) as f:
        new = f.read()
    old = read_live(pid)

    ratio = len(new) / len(old) * 100 if old else 100.0
    print(f"{key}: {len(old)} -> {len(new)} chars ({ratio:.1f}%)", flush=True)
    if ratio < SHRINK_GUARD * 100:
        print(f"  !! DROP >10% — skip push for {key}", flush=True)
        return False
    if dry:
        return True

    d = mcp.call("update_page", {"id": pid, "markdown": new})
    result = d.get("result", {})
    content = result.get("content") or []
    text = content[0].get("text", "") if content else json.dumps(d, ensure_ascii=False)
    is_error = result.get("isError", False)
    print(f"  -> {'ERROR: ' + text[:400] if is_error else 'OK'}", flush=True)
    return not is_error


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    keys = args or sorted(load_pages().keys())

    mcp.init()
    pages = load_pages()
    ok = 0
    for key in keys:
        if push(key, pages, dry):
            ok += 1
    print(f"\n{ok}/{len(keys)} pages {'would be ' if dry else ''}pushed", flush=True)


if __name__ == "__main__":
    main()
