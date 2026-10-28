import json, os

os.makedirs("src", exist_ok=True)
for f in os.listdir("before"):
    if not f.endswith(".md"):
        continue
    d = json.load(open(f"before/{f}"))
    md = d["markdown"]
    with open(f"src/{f}", "w") as out:
        out.write(md)
    # stats: count field:value style bullets
    import re
    fv = len(re.findall(r"^- \*\*[^*]+\*\*", md, re.M))
    print(f"{f}\t{len(md)} chars\t{fv} field-label bullets")
