#!/usr/bin/env python3
"""
DDNS 动态 DNS 更新脚本
功能：获取当前公网 IP、通过 Cloudflare API 更新 DNS 记录
支持：Cloudflare DNS (A 记录)
用法：配合 cron 定期运行，保持动态 IP 与域名同步
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ddns_updater")

# 记录上次 IP 的缓存文件
IP_CACHE_FILE = Path("/tmp/homelab_last_ip.txt")

# 多个获取公网 IP 的服务，提高可靠性
IP_SERVICES = [
    "https://api.ipify.org?format=json",
    "https://httpbin.org/ip",
    "https://api.my-ip.io/v2/ip.json",
    "https://ipinfo.io/json",
    "https://ifconfig.me/ip",
]


@dataclass
class CloudflareConfig:
    """Cloudflare DDNS 配置"""
    api_token: str = ""
    zone_id: str = ""
    record_id: str = ""
    domain: str = "chaose.dpdns.org"
    proxy_enabled: bool = False       # 是否开启 Cloudflare 代理
    ttl: int = 1                      # TTL (1 = 自动)


def load_env(env_path: str = ".env"):
    """加载环境变量文件"""
    env_file = Path(env_path)
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


def get_public_ip() -> str:
    """
    获取当前公网 IP 地址
    依次尝试多个 IP 查询服务，确保可靠性
    :return: 公网 IP 地址
    """
    for service in IP_SERVICES:
        try:
            resp = requests.get(service, timeout=10)
            if resp.status_code == 200:
                data = resp.json() if "json" in service else {}

                # 不同服务返回格式不同，逐一解析
                ip = (
                    data.get("ip")          # ipify, my-ip
                    or data.get("origin")   # httpbin
                    or data.get("ip")       # ipinfo
                    or resp.text.strip()    # ifconfig.me (纯文本)
                )

                # 验证 IP 格式
                if ip and len(ip.split(".")) == 4:
                    logger.info(f"获取公网 IP: {ip} (来源: {service})")
                    return ip.strip()

        except requests.exceptions.RequestException:
            continue
        except (json.JSONDecodeError, KeyError):
            continue

    logger.error("所有 IP 查询服务均不可用！")
    return ""


def get_cached_ip() -> str:
    """读取上次缓存的 IP 地址"""
    try:
        if IP_CACHE_FILE.exists():
            return IP_CACHE_FILE.read_text().strip()
    except Exception:
        pass
    return ""


def save_cached_ip(ip: str):
    """保存当前 IP 到缓存文件"""
    try:
        IP_CACHE_FILE.write_text(ip)
    except Exception as e:
        logger.warning(f"保存 IP 缓存失败: {e}")


class CloudflareDDNS:
    """Cloudflare DDNS 更新客户端"""

    API_BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, config: CloudflareConfig):
        self.config = config
        self.headers = {
            "Authorization": f"Bearer {config.api_token}",
            "Content-Type": "application/json",
        }

    def get_record(self) -> dict:
        """
        获取当前 DNS 记录信息
        :return: DNS 记录信息字典
        """
        url = (
            f"{self.API_BASE}/zones/{self.config.zone_id}"
            f"/dns_records/{self.config.record_id}"
        )

        try:
            resp = requests.get(url, headers=self.headers, timeout=15)
            data = resp.json()

            if data.get("success"):
                return data.get("result", {})
            else:
                errors = data.get("errors", [])
                logger.error(f"获取 DNS 记录失败: {errors}")
                return {}

        except requests.exceptions.RequestException as e:
            logger.error(f"Cloudflare API 请求失败: {e}")
            return {}

    def update_record(self, new_ip: str) -> bool:
        """
        更新 DNS A 记录
        :param new_ip: 新的 IP 地址
        :return: 是否更新成功
        """
        url = (
            f"{self.API_BASE}/zones/{self.config.zone_id}"
            f"/dns_records/{self.config.record_id}"
        )

        payload = {
            "type": "A",
            "name": self.config.domain,
            "content": new_ip,
            "ttl": self.config.ttl,
            "proxied": self.config.proxy_enabled,
        }

        try:
            resp = requests.put(url, headers=self.headers, json=payload, timeout=15)
            data = resp.json()

            if data.get("success"):
                logger.info(
                    f"DNS 记录更新成功: {self.config.domain} -> {new_ip}"
                )
                return True
            else:
                errors = data.get("errors", [])
                logger.error(f"DNS 记录更新失败: {errors}")
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Cloudflare API 请求失败: {e}")
            return False

    def list_records(self) -> list:
        """列出域名下所有 DNS 记录（调试用）"""
        url = (
            f"{self.API_BASE}/zones/{self.config.zone_id}/dns_records"
        )
        params = {"name": self.config.domain}

        try:
            resp = requests.get(
                url, headers=self.headers, params=params, timeout=15
            )
            data = resp.json()
            if data.get("success"):
                return data.get("result", [])
        except Exception:
            pass
        return []


def run_ddns_update(env_path: str = ".env", force: bool = False) -> bool:
    """
    执行 DDNS 更新
    :param env_path: 环境变量文件路径
    :param force: 是否强制更新（即使 IP 未变化）
    :return: 是否成功
    """
    # 加载环境变量
    load_env(env_path)

    # 读取 Cloudflare 配置
    config = CloudflareConfig(
        api_token=os.environ.get("CF_API_TOKEN", ""),
        zone_id=os.environ.get("CF_ZONE_ID", ""),
        record_id=os.environ.get("CF_RECORD_ID", ""),
        domain=os.environ.get("DOMAIN", "chaose.dpdns.org"),
        proxy_enabled=os.environ.get("CF_PROXY", "false").lower() == "true",
        ttl=int(os.environ.get("CF_TTL", "1")),
    )

    if not config.api_token or not config.zone_id or not config.record_id:
        logger.error(
            "缺少必要的 Cloudflare 配置！请设置 CF_API_TOKEN、CF_ZONE_ID、CF_RECORD_ID 环境变量。"
        )
        return False

    # 获取当前公网 IP
    current_ip = get_public_ip()
    if not current_ip:
        logger.error("无法获取公网 IP，DDNS 更新中止。")
        return False

    # 检查 IP 是否变化
    cached_ip = get_cached_ip()
    if current_ip == cached_ip and not force:
        logger.info(f"IP 未变化 ({current_ip})，无需更新。")
        return True

    if cached_ip:
        logger.info(f"IP 已变化: {cached_ip} -> {current_ip}")

    # 更新 DNS 记录
    cf = CloudflareDDNS(config)

    # 先获取当前记录信息
    record = cf.get_record()
    if record:
        logger.info(
            f"当前 DNS 记录: {config.domain} -> {record.get('content', 'N/A')}"
        )

    # 执行更新
    success = cf.update_record(current_ip)

    if success:
        save_cached_ip(current_ip)
        logger.info(f"DDNS 更新完成: {config.domain} = {current_ip}")
    else:
        logger.error("DDNS 更新失败！")

    return success


def main():
    parser = argparse.ArgumentParser(description="Cloudflare DDNS 动态 DNS 更新工具")
    parser.add_argument(
        "--env",
        default=".env",
        help="环境变量文件路径 (默认: .env)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制更新（即使 IP 未变化）",
    )
    parser.add_argument(
        "--show-ip",
        action="store_true",
        help="仅显示当前公网 IP 并退出",
    )
    args = parser.parse_args()

    if args.show_ip:
        ip = get_public_ip()
        if ip:
            print(f"当前公网 IP: {ip}")
        else:
            print("无法获取公网 IP")
        return

    success = run_ddns_update(env_path=args.env, force=args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
