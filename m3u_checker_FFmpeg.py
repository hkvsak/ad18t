# -*- coding: utf-8 -*-
"""
终极 M3U 检测器 v8.0 (最终完美版)
支持 CGTN 全系列 | 强制 FFmpeg 验证 | 防封 IP | 自动重试
"""

import requests
import threading
import queue
import time
import re
import os
import urllib3
import random
import subprocess
import json
from collections import defaultdict

# ================== 屏蔽警告 ==================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
requests.packages.urllib3.disable_warnings()

# ================== 配置区 ==================
TIMEOUT = 15
THREADS = 8
MIN_BYTES = 512
RETRY_COUNT = 1
USE_FFMPEG = True

# FFmpeg 路径（Termux 固定）
FFMPEG_PATH = '/data/data/com.termux/files/usr/bin/ffmpeg'
FFMPEG_AVAILABLE = False
FFMPEG_CMD = None

# 伪装浏览器 UA（关键！）
BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# 全局变量
url_queue = queue.Queue()
valid_list = defaultdict(list)
invalid_list = defaultdict(list)
lock = threading.Lock()
checked_count = 0
total_count = 0

# ================== 自动扫描 Download ==================
DOWNLOAD_DIR = '/storage/emulated/0/Download'
if not os.path.exists(DOWNLOAD_DIR):
    DOWNLOAD_DIR = '/sdcard/Download'
    if not os.path.exists(DOWNLOAD_DIR):
        print("无法访问 Download 文件夹！请检查存储权限。")
        exit(1)

def select_file_auto():
    files = [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR)
             if f.lower().endswith(('.m3u', '.m3u8', '.txt'))]
    if not files:
        print(f"在 {DOWNLOAD_DIR} 中未找到 .m3u/.m3u8/.txt 文件")
        return None
    print(f"在 {DOWNLOAD_DIR} 找到 {len(files)} 个文件：")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {os.path.basename(f)}")
    while True:
        try:
            choice = input(f"\n请输入要检测的文件编号（1-{len(files)}），或回车检测全部：").strip()
            if not choice:
                return files
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                return [files[idx]]
        except:
            pass
        print("输入无效，请重试。")

# ================== M3U 解析器（修复 #EXTM3U 跳过）==================
def parse_m3u(lines):
    entries = []
    current_title = "未知频道"
    current_group = "默认分组"
    for line in lines:
        line = line.strip()
        if not line:  # 只跳过空行
            continue
        if line.startswith("#EXTM3U"):  # 保留 #EXTM3U
            continue
        if line.startswith("#EXTINF:"):
            match = re.search(r'group-title="([^"]*)"', line)
            if match:
                current_group = match.group(1).strip() or "默认分组"
            parts = line.split(",", 1)
            if len(parts) > 1:
                current_title = parts[1].strip()
            continue
        if 'group-title=' in line and not line.startswith("#EXTINF:"):
            match = re.search(r'group-title="([^"]*)"', line)
            if match:
                current_group = match.group(1).strip() or "默认分组"
        if re.match(r'^(https?|rtmp|p3p|rtsp)://', line, re.I):
            entries.append((current_group, current_title, line))
            current_title = "未知频道"
            current_group = "默认分组"
    return entries

# ================== 查找 FFmpeg ==================
def find_ffmpeg():
    global FFMPEG_AVAILABLE, FFMPEG_CMD
    if os.path.exists(FFMPEG_PATH):
        try:
            result = subprocess.run([FFMPEG_PATH, '-version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and 'ffmpeg version' in result.stdout:
                FFMPEG_CMD = [FFMPEG_PATH]
                FFMPEG_AVAILABLE = True
                print(f"FFmpeg 已就绪: {FFMPEG_PATH}")
                return
        except:
            pass
    print("未找到 ffmpeg！请在 Termux 执行：pkg install ffmpeg")
    global USE_FFMPEG
    USE_FFMPEG = False

# ================== 检测线程（最终版）==================
def check_url_worker():
    global checked_count
    session = requests.Session()
    session.headers.update({'User-Agent': BROWSER_UA})
    session.allow_redirects = True

    while True:
        try:
            group, title, url = url_queue.get(timeout=1)
        except queue.Empty:
            break

        ok = False
        resp = None
        force_ffmpeg = False

        # 强制 CGTN 系列使用 FFmpeg
        if any(kw in url.lower() or kw in title.lower() for kw in ['cgtn', '0472.org']):
            force_ffmpeg = True
            print(f"   [关键源，强制 FFmpeg 验证] {title}")

        try:
            resp = session.get(url, timeout=TIMEOUT, stream=True, verify=False,
                             headers={'User-Agent': BROWSER_UA},
                             allow_redirects=True)

            if resp.status_code != 200:
                print(f"   [HTTP {resp.status_code}] {title}")
            else:
                chunk = b""
                try:
                    chunk = resp.raw.read(4096)
                except:
                    pass

                if len(chunk) > 0:
                    text = chunk.decode('utf-8', errors='ignore').strip()
                    if text.startswith('#EXTM3U'):
                        lines = text.splitlines()
                        has_stream = any(line.startswith('#EXT-X-STREAM-INF') for line in lines)
                        has_segment = any(line.startswith('#EXTINF:') or '.m3u8' in line for line in lines)
                        if has_stream or has_segment:
                            ok = True if not force_ffmpeg else False

            # FFmpeg 二次验证
            if (not ok or force_ffmpeg) and USE_FFMPEG and FFMPEG_AVAILABLE:
                try:
                    cmd = FFMPEG_CMD + [
                        '-v', 'quiet', '-print_format', 'json',
                        '-show_format', '-show_streams',
                        '-t', '8',
                        '-user_agent', BROWSER_UA,
                        '-headers', 'Referer: https://www.cgtn.com/\r\n',
                        '-reconnect', '1',
                        '-reconnect_at_eof', '1',
                        '-reconnect_streamed', '1',
                        '-reconnect_delay_max', '5',
                        url
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                    if result.returncode == 0:
                        try:
                            data = json.loads(result.stdout)
                            if data.get('streams') or data.get('format'):
                                ok = True
                                print(f"   [FFmpeg 确认] {title}")
                        except:
                            pass
                    else:
                        print(f"   [FFmpeg 返回码 {result.returncode}] {title}")
                except subprocess.TimeoutExpired:
                    print(f"   [FFmpeg 超时] {title}")
                except Exception as e:
                    print(f"   [FFmpeg 异常] {title}: {e}")

        except Exception as e:
            print(f"   [异常] {title}: {e}")
            ok = False
        finally:
            if resp:
                try: resp.close()
                except: pass

        with lock:
            checked_count += 1
            if ok:
                valid_list[group].append((title, url))
                print(f"有效: {title}")
            else:
                invalid_list[group].append((title, url))
                print(f"失效: {title}")

        time.sleep(random.uniform(0.2, 0.6))
        url_queue.task_done()

# ================== 进度条 ==================
def show_progress():
    while checked_count < total_count:
        with lock:
            done = checked_count
        pct = done / total_count * 100 if total_count > 0 else 0
        print(f"\r[检测中] {done}/{total_count} ({pct:.1f}%)", end="", flush=True)
        time.sleep(0.5)
    print(f"\r[完成] {checked_count}/{total_count} (100%)      ")

# ================== 主函数 ==================
def main():
    global total_count
    print("="*60)
    print("M3U 检测器 v8.0 (最终完美版)")
    print("   支持 CGTN 全系列 | 强制 FFmpeg 验证 | 防封 IP")
    print("="*60)

    find_ffmpeg()
    file_list = select_file_auto()
    if not file_list:
        return

    all_entries = []
    for file_path in file_list:
        print(f"\n正在解析：{os.path.basename(file_path)}")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            entries = parse_m3u(lines)
            if entries:
                print(f"  → 解析出 {len(entries)} 条频道")
                all_entries.extend([(file_path, *e) for e in entries])
            else:
                print("  → 无有效频道")
        except Exception as e:
            print(f"  → 读取失败: {e}")

    if not all_entries:
        print("\n未找到任何可检测的频道")
        return

    print(f"\n共 {len(all_entries)} 条待检测，开始多线程检测...\n")
    total_count = len(all_entries)
    for item in all_entries:
        _, group, title, url = item
        url_queue.put((group, title, url))

    start_time = time.time()
    threading.Thread(target=show_progress, daemon=True).start()

    threads = [threading.Thread(target=check_url_worker, daemon=True)
               for _ in range(min(THREADS, total_count))]
    for t in threads: t.start()
    for t in threads: t.join()

    # 输出结果
    output_dir = DOWNLOAD_DIR
    all_groups = set(valid_list.keys()) | set(invalid_list.keys())
    for group in sorted(all_groups):
        safe_name = re.sub(r'[\/:*?"<>|]', '_', group)
        valid_path = os.path.join(output_dir, f"{safe_name}_有效.m3u")
        invalid_path = os.path.join(output_dir, f"{safe_name}_失效.m3u")

        with open(valid_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for t, u in valid_list[group]:
                f.write(f"#EXTINF:-1 group-title=\"{group}\",{t}\n{u}\n")
        with open(invalid_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for t, u in invalid_list[group]:
                f.write(f"#EXTINF:-1 group-title=\"{group}\",{t}\n{u}\n")

        v_count = len(valid_list[group])
        i_count = len(invalid_list[group])
        print(f"分组 '{group}' → {v_count} 有效 | {i_count} 失效")

    duration = time.time() - start_time
    total_valid = sum(len(v) for v in valid_list.values())
    total_invalid = sum(len(v) for v in invalid_list.values())
    print("\n" + "="*60)
    print(f"检测完成！有效 {total_valid}，失效 {total_invalid}，用时 {duration:.1f}s")
    print(f"结果已保存至：{output_dir}")
    print("="*60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户已中断。")
    except Exception as e:
        print(f"\n程序异常: {e}")
