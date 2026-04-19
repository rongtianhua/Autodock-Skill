# macOS PPID=1 进程与 kill 命令

## 什么是 PPID=1 进程

在 macOS 中，**PPID=1 的进程**是由 `launchd`（系统初始化进程）托管的服务。这些服务不能通过普通信号终止，因为 launchd 会忽略常规终止信号并自动重启服务。

## 典型场景

Docker Desktop 的 Lima VM 进程由 launchd 托管：

```
PID 8813  PPID=1  limactl hostagent (docker-desktop-linux)
```

普通 `kill <PID>` → **无效**，进程被 launchd 保留

## 解决方案

```bash
# 强制终止（需管理员权限）
sudo kill -9 <PID>

# 或者一次性清理所有 limactl 进程（需确认不是 Colima）
sudo pkill -9 limactl
```

## 如何区分 Docker Desktop vs Colima 进程

执行 `ps aux | grep limactl`，查看完整命令行：

| 进程名 | 来源 | 操作 |
|--------|------|------|
| `docker-desktop-linux` 开头 | Docker Desktop | ✅ 可杀 |
| `colima` 开头 | Colima | ❌ 保留 |

## 误操作恢复

如果误杀了 Colima：
```bash
colima start
docker context use colima
```

## 彻底禁用 Docker Desktop 服务

如果只是想禁用 Docker Desktop 自启，而不是临时杀进程：
```bash
# 查看 launchd 服务
launchctl list | grep docker

# 禁用服务（需要管理员权限）
sudo launchctl disable <service-name>
```

然后再杀 VM 进程就不会被自动重启了。
