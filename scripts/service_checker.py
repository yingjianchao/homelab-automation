#!/usr/bin/env python3
"""关键服务状态检查 - FRP、WireGuard、AdGuard、Docker 等"""
import argparse, subprocess, requests, sys

def check_port(host, port, timeout=3):
    """检查端口是否开放"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except:
        return False

def check_frp(dashboard="http://127.0.0.1:7500", user="admin", password=""):
    """检查 FRP 隧道状态"""
    print("🔗 FRP 状态:")
    try:
        r = requests.get(f"{dashboard}/api/proxy/tcp", auth=(user, password), timeout=5)
        if r.status_code == 200:
            proxies = r.json().get("proxies", [])
            for p in proxies:
                status = "✅" if p.get("status") == "running" else "❌"
                print(f"  {status} {p[\'name\']:20} → {p.get(\'remote_port\', \'?\')}")
            if not proxies:
                print("  ℹ️  没有活跃隧道")
        else:
            print(f"  ❌ Dashboard 响应异常: {r.status_code}")
    except Exception as e:
        print(f"  ❌ 无法连接 Dashboard: {e}")

def check_wireguard(host="10.0.0.1"):
    """检查 WireGuard 状态"""
    print("\n🔒 WireGuard 状态:")
    try:
        r = requests.get(f"http://{host}/cgi-bin/luci/admin/network/wireguard", timeout=5)
        if r.status_code == 200:
            print("  ✅ WireGuard 接口可访问")
        else:
            print(f"  ⚠️  HTTP {r.status_code}")
    except:
        # 端口检查作为 fallback
        if check_port(host, 51820):
            print("  ✅ 端口 51820 开放")
        else:
            print("  ❌ 端口 51820 未开放")

def check_adguard(host="10.0.0.1"):
    """检查 AdGuard Home"""
    print("\n🛡️  AdGuard Home:")
    try:
        r = requests.get(f"http://{host}:3000/control/status", timeout=5)
        if r.status_code == 200:
            data = r.json()
            print(f"  ✅ 运行中 (DNS 查询: {data.get(\'num_dns_queries\', \'?\')})")
        else:
            print(f"  ⚠️  HTTP {r.status_code}")
    except:
        if check_port(host, 53):
            print("  ✅ DNS 端口 53 可用")
        else:
            print("  ❌ AdGuard 不可达")

def check_docker(host, user="root", port=22):
    """检查 Docker 容器"""
    print(f"\n🐳 Docker ({host}):")
    try:
        r = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", "-p", str(port),
                           f"{user}@{host}", "docker ps --format '{{.Names}}: {{.Status}}'"],
                          capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            containers = r.stdout.strip().split("\n")
            for c in containers:
                if c.strip():
                    print(f"  ✅ {c}")
            if not containers:
                print("  ℹ️  没有运行中的容器")
        else:
            print(f"  ❌ SSH 连接失败")
    except Exception as e:
        print(f"  ❌ {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="服务状态检查")
    p.add_argument("--frp", action="store_true", help="检查 FRP")
    p.add_argument("--wg", action="store_true", help="检查 WireGuard")
    p.add_argument("--adguard", action="store_true", help="检查 AdGuard")
    p.add_argument("--docker", help="检查 Docker (SSH host)")
    p.add_argument("--all", action="store_true", help="检查全部")
    args = p.parse_args()

    if args.all or args.frp: check_frp()
    if args.all or args.wg: check_wireguard()
    if args.all or args.adguard: check_adguard()
    if args.docker: check_docker(args.docker)
    if args.all: check_docker("192.168.1.33", "yingjianchao")
    if not any([args.frp, args.wg, args.adguard, args.docker, args.all]):
        p.print_help()
