import json, os, sys, mcp

mcp.init()

def push(key, dry=False):
    old = open(f"src/{key}.md").read()
    new = open(f"after/{key}.md").read()
    ratio = len(new) / len(old) * 100
    PAGES = json.load(open("pages.json"))
    pid = PAGES[key]
    print(f"{key}: {len(old)} -> {len(new)} chars ({ratio:.1f}%)", flush=True)
    if ratio < 90:
        print(f"  !! DROP >10% — skip push for {key}", flush=True)
        return False
    if dry:
        return True
    d = mcp.call("update_page", {"id": pid, "markdown": new})
    txt = d["result"]["content"][0]["text"] if d.get("result", {}).get("content") else json.dumps(d)
    iserr = d.get("result", {}).get("isError", False)
    print(f"  -> {'ERROR: ' + txt[:300] if iserr else 'OK'}", flush=True)
    return not iserr

if __name__ == "__main__":
    dry = "--dry" in sys.argv
    keys = [a for a in sys.argv[1:] if not a.startswith("--")]
    for k in keys:
        push(k, dry)
