#!/usr/bin/env python3
"""网络拓扑发现 - 自动扫描并生成拓扑图"""
import argparse, subprocess, socket, sys
from concurrent.futures import ThreadPoolExecutor

def ping_host(ip):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "1", str(ip)],
                          capture_output=True, timeout=3)
        if r.returncode == 0:
            try:
                hostname = socket.gethostbyaddr(str(ip))[0]
            except:
                hostname = ""
            return {"ip": str(ip), "hostname": hostname, "status": "online"}
    except: pass
    return None

def scan_network(network_base="192.168.1", start=1, end=254):
    """扫描网段"""
    print(f"🔍 扫描 {network_base}.{start}-{end} ...")
    ips = [f"{network_base}.{i}" for i in range(start, end+1)]

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(ping_host, ips))

    devices = [r for r in results if r]
    print(f"\n📊 发现 {len(devices)} 台在线设备:\n")
    for d in devices:
        host = d["hostname"] or "(未知)"
        print(f"  {d[\'ip\']:18} {host}")
    return devices

def gen_mermaid(devices, output="topology.md"):
    """生成 Mermaid 拓扑图"""
    known = {
        "10.0.0.1": "iStoreOS\n(主路由)",
        "192.168.1.33": "飞牛NAS",
        "192.168.1.35": "OpenWrt\n(旁路由)",
        "192.168.1.47": "华为信创",
        "192.168.1.254": "Ruijie\n(WiFi路由)",
    }

    md = "# 网络拓扑\n\n```mermaid\ngraph TD\n"
    md += "    Internet((Internet)) --> R1[iStoreOS<br>10.0.0.1]\n"
    md += "    R1 --> SW[交换机/局域网]\n"

    for d in devices:
        ip = d["ip"]
        label = known.get(ip, d.get("hostname", ip))
        safe_id = ip.replace(".", "_")
        if ip == "10.0.0.1":
            continue  # 已经画了
        md += f"    SW --> {safe_id}[{label}<br>{ip}]\n"

    md += "```\n\n"
    md += "## 在线设备列表\n\n| IP | 主机名 | 状态 |\n|---|---|---|\n"
    for d in devices:
        md += f"| {d[\'ip\']} | {d.get(\'hostname\', \'-\')} | ✅ |\n"

    with open(output, "w") as f:
        f.write(md)
    print(f"\n📝 拓扑图已保存: {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="网络拓扑发现")
    p.add_argument("--network", default="192.168.1", help="网段前缀")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=254)
    p.add_argument("--mermaid", action="store_true", help="生成 Mermaid 图")
    args = p.parse_args()

    devices = scan_network(args.network, args.start, args.end)
    if args.mermaid:
        gen_mermaid(devices)
