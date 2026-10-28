import json, mcp

mcp.init()
PAGES = json.load(open("pages.json"))

CHECK_STRINGS = {
    "spec-5": ["17.842,59", "21.740", "1.300.000", "0,32", "5.071.744", "LONG MINH", "2,5%", "half-up", "823.250"],
    "spec-2": ["Long Minh", "5753", "V32", "Idempotency-Key", "3.500.000"],
    "spec-8": ["5753", "3.500.000", "sage please make it global rule"],
    "spec-1": ["17/09/2026", "09/09/2026", "01/10/2026", "Idempotency-Key"],
    "spec-3": ["declarationNumber", "GLC", "draft_ui"],
    "spec-4": ["DIS-09", "44–48px", "SAGE"],
    "spec-6": ["AC-CP-KT-19", "14 ngày", "5753"],
    "spec-7": ["DIS-10", "ENV-01", "LCL-07"],
    "lcl": ["rev_group_id", "cost_group_id", "409"],
    "spec-tt": ["TTransport", "27/10/2026"],
    "changelog": ["customs_declaration_no", "26/10/2026"],
    "index": ["logic-nghi-p-v-h-ng-l-lcl.md"],
}

for key, pid in PAGES.items():
    d = mcp.call("read_page", {"id": pid})
    text = d["result"]["content"][0]["text"]
    try:
        text = json.loads(text).get("markdown", text)
    except Exception:
        pass
    open(f"verify2/{key}.md", "w") if __import__("os").path.isdir("verify2") or __import__("os").makedirs("verify2", exist_ok=True) else None
    open(f"verify2/{key}.md", "w").write(text)
    missing = [s for s in CHECK_STRINGS.get(key, []) if s not in text]
    print(f"{key:10} len={len(text):>6}  missing-checks: {missing if missing else 'NONE'}")
