#!/usr/bin/env python3
"""设备健康监控 - Ping/HTTP/SSH 检查，异常报警"""
import argparse, subprocess, yaml, json, sys, os, time
from datetime import datetime

def load_devices(config_path="config/devices.yaml"):
    with open(config_path) as f:
        return yaml.safe_load(f)["devices"]

def ping_check(host, count=2):
    """Ping 检查"""
    try:
        r = subprocess.run(["ping", "-c", str(count), "-W", "2", host],
                          capture_output=True, timeout=10)
        if r.returncode == 0:
            # 解析延迟
            for line in r.stdout.decode().split("\n"):
                if "avg" in line:
                    avg = line.split("/")[4]
                    return {"status": "online", "latency": f"{avg}ms"}
            return {"status": "online", "latency": "?"}
        return {"status": "offline", "latency": None}
    except:
        return {"status": "error", "latency": None}

def http_check(url, timeout=5):
    """HTTP 健康检查"""
    import requests
    try:
        r = requests.get(url, timeout=timeout)
        return {"status": "online", "code": r.status_code, "time": f"{r.elapsed.total_seconds():.2f}s"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:50]}

def ssh_check(host, user, port=22):
    """SSH 连接检查"""
    try:
        r = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                           "-p", str(port), f"{user}@{host}", "echo ok"],
                          capture_output=True, timeout=10)
        if r.returncode == 0 and "ok" in r.stdout.decode():
            return {"status": "online"}
        return {"status": "auth_failed"}
    except:
        return {"status": "offline"}

def monitor_all(config_path="config/devices.yaml", output_json=False):
    """监控所有设备"""
    devices = load_devices(config_path)
    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"🔍 设备健康检查 [{now}]\n")

    for dev in devices:
        name = dev["name"]
        host = dev["host"]
        print(f"  {name:16} ({host:16})", end=" ")

        # Ping
        ping = ping_check(host)
        status = ping["status"]
        latency = ping.get("latency", "")

        # HTTP（如果有 web 配置）
        http = None
        if "web" in dev:
            url = dev["web"].get("url", f"http://{host}")
            http = http_check(url)

        # SSH（如果有 ssh 配置）
        ssh = None
        ssh_cfg = dev.get("ssh", {})
        if ssh_cfg.get("enabled"):
            ssh = ssh_check(host, ssh_cfg.get("user", "root"), ssh_cfg.get("port", 22))

        # 汇总状态
        all_ok = status == "online"
        if http and http["status"] != "online": all_ok = False
        if ssh and ssh["status"] != "online": all_ok = False

        icon = "✅" if all_ok else "⚠️" if status == "online" else "❌"
        print(f"{icon} {status:8} ping={latency or \'?\':8}", end="")
        if http: print(f" http={http[\'status\']}", end="")
        if ssh: print(f" ssh={ssh[\'status\']}", end="")
        print()

        results.append({"name": name, "host": host, "ping": ping, "http": http, "ssh": ssh})

    if output_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="设备健康监控")
    p.add_argument("--config", default="config/devices.yaml")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    monitor_all(args.config, args.json)
