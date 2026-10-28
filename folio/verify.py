import json, re, os, mcp

mcp.init()
PAGES = json.load(open("pages.json"))

FORBIDDEN = [
    "**Bước:**",
    "**Không được suy ra",
    "- **Sự kiện được ghi nhận",
    "**Sự kiện được ghi nhận:**",
    "**Điểm kiểm tra:**",
    "**Tình huống:**",
    "**Đối tượng:**",
    "**Quy tắc:**",
    "**Mã:**",
    "**Trạng thái lô:**",
    "**Điều kiện vào:**",
    "**Hệ quả:**",
    "**Điểm còn mở:**",
    "**Thành phần:**",
    "**Vai trò:**",
    "**Nhu cầu chính:**",
    "**Thuật ngữ:**",
    "**Mảng nghiệp vụ:**",
    "**Sự kiện trên trục:**",
    "**Ký hiệu:**",
    "**Bề mặt:**",
    "**Thực thể (bảng/màn):**",
    "**Báo cáo / màn:**",
    "**Ngày:**",
    "**STT:**",
    "**Hạng mục:**",
    "**Quyết định (nguyên văn",
    "**Đối tượng áp dụng:**",
    "**Chế độ:**",
    "**Band:**",
    "**Chứng từ:**",
    "**Bắt buộc?:**",
    "**Tuyến (nhà máy đích):**",
    "**Loại xe:**",
    "**Nhóm:**",
    "**Cột:**",
    "**Nguồn:**",
    "**Quy tắc chặn",
]

print(f"{'page':10} {'len_old':>8} {'len_new':>8} {'%':>6} {'links o/n':>10} {'mermaid o/n':>12} {'heads o/n':>10} {'forbidden':>9}")
report = []
for key, pid in PAGES.items():
    old = open(f"src/{key}.md").read()
    d = mcp.call("read_page", {"id": pid})
    new = d["result"]["content"][0]["text"]
    # read_page returns markdown inside JSON? check
    try:
        parsed = json.loads(new)
        new = parsed.get("markdown", new)
    except Exception:
        pass
    open(f"verify/{key}.md", "w") if os.path.isdir("verify") or os.makedirs("verify", exist_ok=True) else None
    open(f"verify/{key}.md", "w").write(new)

    pct = len(new) / len(old) * 100
    lo = len(re.findall(r"\[[^\]]+\]\([^)]+\)", old))
    ln = len(re.findall(r"\[[^\]]+\]\([^)]+\)", new))
    mo = old.count("```mermaid")
    mn = new.count("```mermaid")
    ho = len(re.findall(r"^#{1,6} ", old, re.M))
    hn = len(re.findall(r"^#{1,6} ", new, re.M))
    bad = [f for f in FORBIDDEN if f in new]
    flag = ""
    if pct < 90: flag += " LEN<90%"
    if ln < lo: flag += " LINKS-LOST"
    if mn < mo: flag += " MERMAID-LOST"
    if hn < ho: flag += " HEADS-LOST"
    if bad: flag += f" FORBIDDEN:{bad[:3]}"
    print(f"{key:10} {len(old):>8} {len(new):>8} {pct:>5.1f}% {lo:>5}/{ln:<4} {mo:>6}/{mn:<6} {ho:>5}/{hn:<5} {len(bad):>9}{flag}")
    report.append((key, pct, len(bad), flag))

print()
ok = True
for key, pct, bad, flag in report:
    status = "PASS" if (pct >= 90 and bad == 0 and "LOST" not in flag) else "FAIL"
    if status == "FAIL": ok = False
    print(f"{status}  {key}: {pct:.1f}% len, {bad} forbidden patterns{flag}")
print()
print("ALL PASS" if ok else "SOME FAILED")
