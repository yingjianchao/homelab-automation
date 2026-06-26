# 🔧 HomeLab-Automation — 家庭实验室自动化

设备监控、网络拓扑管理、自动备份、DDNS 更新、服务状态检查。

## 架构

```
                    ┌─────────────────────┐
                    │   chaose.dpdns.org   │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │  iStoreOS 10.0.0.1  │
                    │  (主路由/FRPS/WG)    │
                    └──────────┬──────────┘
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────┴──────┐ ┌──────┴───────┐ ┌──────┴───────┐
    │ OpenWrt        │ │ 飞牛 NAS     │ │ 华为信创     │
    │ 192.168.1.35   │ │ 192.168.1.33 │ │ 192.168.1.47 │
    │ (FRPC/WG)      │ │ (SMB/Docker) │ │ (FileBrowser)│
    └────────────────┘ └──────────────┘ └──────────────┘
```

## 工具

| 脚本 | 功能 |
|------|------|
| `device_monitor.py` | 设备健康监控（Ping/HTTP/SSH） |
| `network_topo.py` | 网络拓扑自动发现 |
| `backup_manager.py` | 路由器配置自动备份 |
| `ddns_updater.py` | 动态 DNS 更新 |
| `service_checker.py` | 关键服务状态检查 |

## 快速开始

```bash
cp config/example.env .env
# 编辑 .env 填入你的设备信息

# 检查所有设备状态
python scripts/device_monitor.py

# 查看网络拓扑
python scripts/network_topo.py

# 备份路由器配置
python scripts/backup_manager.py --all

# 检查服务状态
python scripts/service_checker.py
```

## License

MIT
