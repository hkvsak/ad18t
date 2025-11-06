import os
import re
import sys
from collections import defaultdict

OUTPUT_DIR = "m3u_output"

def choose_input_file():
    files = [f for f in os.listdir('.') if f.lower().endswith(('.m3u', '.m3u8', '.txt'))]
    if not files:
        print("❌ 未检测到可处理的输入文件（支持 .m3u / .m3u8 / .txt）")
        sys.exit(1)
    if len(files) == 1:
        print(f"📄 自动检测到输入文件: {files[0]}")
        return files[0]
    print("\n📁 检测到多个输入文件：")
    for i, name in enumerate(files, 1):
        print(f"  {i}. {name}")
    while True:
        try:
            idx = int(input("\n请输入要处理的文件编号："))
            if 1 <= idx <= len(files):
                print(f"✅ 已选择文件：{files[idx - 1]}")
                return files[idx - 1]
        except ValueError:
            pass
        print("⚠️ 请输入有效编号。")

def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name.strip())

def normalize_group(name):
    """提取频道或分类前缀，如 '松视1' -> '松视'"""
    n = re.sub(r'[\d\s\W_]+', '', name)
    return n if n else "未分类"

def parse_any_format(file):
    """自动识别格式并提取 (group, title, url)"""
    with open(file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [l.strip() for l in f if l.strip()]
    entries = []

    # 模式1：标准 M3U 格式
    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF"):
            m = re.search(r',\s*(.+)$', lines[i])
            if m and i + 1 < len(lines):
                title = m.group(1).strip()
                url = lines[i + 1].strip()
                if re.match(r'^(https?|p3p|rtmp)://', url):
                    entries.append((normalize_group(title), title, url))

    # 模式2：非标准 [分类] 名称,URL 格式
    pattern_custom = re.compile(r'^\[([^\]]+)\]\s*(.+?),\s*(https?://.*)', re.IGNORECASE)
    pattern_simple = re.compile(r'^(.+?),\s*(https?://.*)', re.IGNORECASE)

    for line in lines:
        if not line.startswith("#"):
            m = pattern_custom.match(line)
            if m:
                group, title, url = m.groups()
                entries.append((group.strip(), title.strip(), url.strip()))
                continue
            m2 = pattern_simple.match(line)
            if m2:
                title, url = m2.groups()
                entries.append((normalize_group(title), title.strip(), url.strip()))

    return entries

def remove_duplicates(entries):
    seen = set()
    unique = []
    for g, t, u in entries:
        key = (normalize_group(g).lower(), u.lower())
        if key not in seen:
            seen.add(key)
            unique.append((g, t, u))
    return unique

def group_and_output(file):
    entries = parse_any_format(file)
    if not entries:
        print("❌ 未检测到有效频道，请检查文件格式（支持 #EXTINF 或 [分类] 名称,URL）")
        return
    print(f"📦 共解析到 {len(entries)} 条频道。")

    entries = remove_duplicates(entries)
    print(f"🧹 去重后剩余 {len(entries)} 条。")

    grouped = defaultdict(list)
    for group, title, url in entries:
        grouped[group].append((title, url))

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\n📂 输出结果：")
    for group, items in grouped.items():
        safe_name = sanitize_filename(group)
        outfile = os.path.join(OUTPUT_DIR, f"{safe_name}.m3u")
        with open(outfile, 'w', encoding='utf-8-sig') as f:
            f.write("#EXTM3U\n")
            for title, url in items:
                f.write(f'#EXTINF:-1 group-title="{group}",{title}\n{url}\n')
        print(f"  ✅ {outfile} -> {len(items)} 条")

    print(f"\n📁 所有结果已保存到：{os.path.abspath(OUTPUT_DIR)}")

if __name__ == "__main__":
    filename = choose_input_file()
    group_and_output(filename)