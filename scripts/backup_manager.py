#!/usr/bin/env python3
"""
自动备份管理脚本
功能：备份路由器配置（iStoreOS/OpenWrt）、NAS 数据、生成备份报告
支持 SSH 远程备份、rsync 同步、本地归档
"""

import argparse
import hashlib
import logging
import os
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backup_manager")


@dataclass
class BackupTarget:
    """备份目标"""
    name: str
    host: str
    device_type: str = "generic"
    backup_method: str = "ssh"         # ssh / rsync / scp
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_key: str = "~/.ssh/id_rsa"
    source_paths: list = field(default_factory=list)
    backup_enabled: bool = True
    # OpenWrt 特有配置
    openwrt_backup: bool = False       # 是否通过 OpenWrt API 备份


@dataclass
class BackupManagerConfig:
    """备份管理配置"""
    targets: list = field(default_factory=list)
    backup_dir: str = "/tmp/homelab-backups"
    retention_days: int = 30           # 备份保留天数
    max_backups: int = 50              # 最大备份数量
    compress: bool = True
    notify_on_failure: bool = True


def load_config(config_path: str, env_path: str = ".env") -> BackupManagerConfig:
    """加载备份配置"""
    # 加载环境变量
    env_file = Path(env_path)
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    config = BackupManagerConfig()

    # 备份存储目录
    config.backup_dir = os.environ.get("BACKUP_DIR", "/tmp/homelab-backups")
    config.retention_days = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))

    # 解析设备列表
    for dev in data.get("devices", []):
        if not dev.get("backup_enabled", False):
            continue

        config.targets.append(
            BackupTarget(
                name=dev.get("name", dev["host"]),
                host=dev["host"],
                device_type=dev.get("type", "generic"),
                ssh_user=dev.get("ssh_user", "root"),
                ssh_port=dev.get("ssh_port", 22),
                ssh_key=dev.get("ssh_key", "~/.ssh/id_rsa"),
                source_paths=dev.get("backup_paths", []),
                backup_enabled=dev.get("backup_enabled", False),
                openwrt_backup=dev.get("openwrt_backup", False),
            )
        )

    return config


def run_ssh_command(host: str, command: str, user: str = "root",
                    port: int = 22, key: str = "~/.ssh/id_rsa") -> tuple[bool, str]:
    """
    通过 SSH 执行远程命令
    :return: (是否成功, 输出内容)
    """
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-i", os.path.expanduser(key),
        "-p", str(port),
        f"{user}@{host}",
        command,
    ]

    try:
        result = subprocess.run(
            ssh_cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return True, result.stdout
        logger.error(f"SSH 命令失败 [{host}]: {result.stderr}")
        return False, result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"SSH 命令超时 [{host}]")
        return False, "命令执行超时"
    except Exception as e:
        logger.error(f"SSH 连接失败 [{host}]: {e}")
        return False, str(e)


def backup_openwrt_config(target: BackupTarget, backup_dir: str) -> Optional[str]:
    """
    备份 OpenWrt/iStoreOS 路由器配置
    通过 SSH 执行 sysupgrade -b 命令生成配置备份
    :return: 本地备份文件路径
    """
    logger.info(f"开始备份 OpenWrt 配置: {target.name} ({target.host})")

    # 在远程设备上生成配置备份
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    remote_path = f"/tmp/backup_{target.name}_{timestamp}.tar.gz"

    # 方法1: 使用 sysupgrade -b 备份（OpenWrt / iStoreOS）
    success, output = run_ssh_command(
        target.host,
        f"sysupgrade -b {remote_path}",
        user=target.ssh_user,
        port=target.ssh_port,
        key=target.ssh_key,
    )

    if not success:
        # 方法2: 手动打包 /etc/config 目录作为备选方案
        logger.warning("sysupgrade 备份失败，尝试手动打包 /etc/config ...")
        success, output = run_ssh_command(
            target.host,
            f"tar czf {remote_path} /etc/config /etc/shadow /etc/passwd "
            f"/etc/dropbear /etc/rc.local /etc/crontabs 2>/dev/null || true",
            user=target.ssh_user,
            port=target.ssh_port,
            key=target.ssh_key,
        )

    if not success:
        logger.error(f"备份 OpenWrt 配置失败: {target.name}")
        return None

    # 通过 SCP 下载备份文件到本地
    local_dir = os.path.join(backup_dir, target.name)
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, f"openwrt_backup_{timestamp}.tar.gz")

    scp_cmd = [
        "scp",
        "-o", "StrictHostKeyChecking=no",
        "-i", os.path.expanduser(target.ssh_key),
        "-P", str(target.ssh_port),
        f"{target.ssh_user}@{target.host}:{remote_path}",
        local_path,
    ]

    try:
        subprocess.run(scp_cmd, capture_output=True, text=True, timeout=60, check=True)
        logger.info(f"OpenWrt 配置已下载到: {local_path}")
    except Exception as e:
        logger.error(f"SCP 下载失败: {e}")
        return None
    finally:
        # 清理远程临时文件
        run_ssh_command(
            target.host,
            f"rm -f {remote_path}",
            user=target.ssh_user,
            port=target.ssh_port,
            key=target.ssh_key,
        )

    return local_path


def backup_via_rsync(target: BackupTarget, backup_dir: str) -> Optional[str]:
    """
    通过 rsync 同步备份文件
    :return: 本地备份目录路径
    """
    logger.info(f"开始 rsync 备份: {target.name} ({target.host})")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_dir = os.path.join(backup_dir, target.name, f"rsync_{timestamp}")
    os.makedirs(local_dir, exist_ok=True)

    ssh_key = os.path.expanduser(target.ssh_key)

    for source_path in target.source_paths:
        logger.info(f"  同步路径: {source_path}")

        rsync_cmd = [
            "rsync",
            "-avz",
            "--timeout=60",
            "-e",
            f"ssh -o StrictHostKeyChecking=no -i {ssh_key} -p {target.ssh_port}",
            f"{target.ssh_user}@{target.host}:{source_path}",
            local_dir,
        ]

        try:
            result = subprocess.run(
                rsync_cmd, capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                logger.info(f"  同步完成: {source_path}")
            else:
                logger.warning(f"  同步警告: {result.stderr}")
        except subprocess.TimeoutExpired:
            logger.error(f"  rsync 超时: {source_path}")
        except Exception as e:
            logger.error(f"  rsync 失败: {e}")

    return local_dir


def backup_via_ssh(target: BackupTarget, backup_dir: str) -> Optional[str]:
    """
    通过 SSH 打包远程文件并下载
    :return: 本地备份文件路径
    """
    logger.info(f"开始 SSH 备份: {target.name} ({target.host})")

    if not target.source_paths:
        logger.warning(f"未配置备份路径: {target.name}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    remote_tar = f"/tmp/backup_{target.name}_{timestamp}.tar.gz"

    # 在远程打包文件
    paths_str = " ".join(target.source_paths)
    cmd = f"tar czf {remote_tar} {paths_str} 2>/dev/null || true"
    success, _ = run_ssh_command(
        target.host, cmd,
        user=target.ssh_user, port=target.ssh_port, key=target.ssh_key,
    )

    if not success:
        return None

    # 下载到本地
    local_dir = os.path.join(backup_dir, target.name)
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, f"backup_{timestamp}.tar.gz")

    scp_cmd = [
        "scp",
        "-o", "StrictHostKeyChecking=no",
        "-i", os.path.expanduser(target.ssh_key),
        "-P", str(target.ssh_port),
        f"{target.ssh_user}@{target.host}:{remote_tar}",
        local_path,
    ]

    try:
        subprocess.run(scp_cmd, capture_output=True, text=True, timeout=120, check=True)
        logger.info(f"备份已下载到: {local_path}")
    except Exception as e:
        logger.error(f"下载备份失败: {e}")
        return None
    finally:
        run_ssh_command(
            target.host, f"rm -f {remote_tar}",
            user=target.ssh_user, port=target.ssh_port, key=target.ssh_key,
        )

    return local_path


def calculate_file_hash(filepath: str) -> str:
    """计算文件 MD5 哈希"""
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def cleanup_old_backups(backup_dir: str, retention_days: int, max_backups: int):
    """清理过期的旧备份"""
    if not os.path.exists(backup_dir):
        return

    now = datetime.now()
    removed = 0

    for root, dirs, files in os.walk(backup_dir, topdown=False):
        for name in files:
            filepath = os.path.join(root, name)
            try:
                # 检查文件修改时间
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                age_days = (now - mtime).days
                if age_days > retention_days:
                    os.remove(filepath)
                    removed += 1
                    logger.info(f"已删除过期备份 ({age_days} 天): {filepath}")
            except Exception as e:
                logger.warning(f"清理备份时出错: {e}")

    # 清理空目录
    for root, dirs, files in os.walk(backup_dir, topdown=False):
        if not dirs and not files and root != backup_dir:
            os.rmdir(root)

    if removed:
        logger.info(f"共清理 {removed} 个过期备份")


def run_backup(config: BackupManagerConfig):
    """执行所有备份任务"""
    os.makedirs(config.backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = []

    logger.info(f"=" * 60)
    logger.info(f"开始自动备份任务 - {timestamp}")
    logger.info(f"备份目录: {config.backup_dir}")
    logger.info(f"待备份目标: {len(config.targets)} 个")
    logger.info(f"=" * 60)

    for target in config.targets:
        if not target.backup_enabled:
            continue

        result_path = None

        try:
            # 根据设备类型选择备份方式
            if target.device_type == "router" and target.openwrt_backup:
                result_path = backup_openwrt_config(target, config.backup_dir)
            elif target.backup_method == "rsync":
                result_path = backup_via_rsync(target, config.backup_dir)
            else:
                result_path = backup_via_ssh(target, config.backup_dir)

            status = "成功" if result_path else "失败"
            results.append((target.name, status, result_path or "无"))

        except Exception as e:
            logger.error(f"备份 {target.name} 时出错: {e}")
            results.append((target.name, "异常", str(e)))

    # 清理过期备份
    cleanup_old_backups(config.backup_dir, config.retention_days, config.max_backups)

    # 打印备份报告
    print("\n" + "=" * 60)
    print(f"  备份报告 - {timestamp}")
    print("=" * 60)
    for name, status, path in results:
        icon = "✅" if status == "成功" else "❌"
        print(f"  {icon} {name:<20} [{status}]  {path}")
    print("=" * 60)

    return all(r[1] == "成功" for r in results)


def main():
    parser = argparse.ArgumentParser(description="家庭实验室自动备份管理工具")
    parser.add_argument(
        "--config", "-c",
        default="config/devices.yaml",
        help="设备配置文件路径 (默认: config/devices.yaml)",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="环境变量文件路径 (默认: .env)",
    )
    parser.add_argument(
        "--backup-dir", "-d",
        help="备份存储目录（覆盖配置文件中的设置）",
    )
    parser.add_argument(
        "--retention",
        type=int,
        help="备份保留天数（覆盖配置文件中的设置）",
    )
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config, args.env)

    # 命令行参数覆盖
    if args.backup_dir:
        config.backup_dir = args.backup_dir
    if args.retention:
        config.retention_days = args.retention

    if not config.targets:
        logger.warning("未配置任何备份目标！请检查 devices.yaml 中 backup_enabled 设置。")
        sys.exit(0)

    # 执行备份
    success = run_backup(config)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
