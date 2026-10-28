import json, sys

d = json.load(open("tree.json"))
text = d["result"]["content"][0]["text"]
tree = json.loads(text)

docs = []

def walk(nodes, depth=0):
    for n in nodes:
        if n.get("kind") == "folder":
            print("  " * depth + "[FOLDER] " + n["title"])
        else:
            docs.append(n)
            print("  " * depth + n["id"] + "  |  " + str(n.get("kind")) + "  |  " + n["title"])
        walk(n.get("children", []), depth + 1)

walk(tree)
print()
print("DOC COUNT:", len(docs))
