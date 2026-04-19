---
name: "mac-memory-optimization-ollama-docker"
description: "Mac mini 内存优化与容器管理（Docker/Colima/Ollama）。当用户需要检查 macOS 系统内存占用、清理 Docker Desktop 冗余进程、管理 Ollama 模型、优化 16GB Mac mini 内存使用、或者遇到 Docker Desktop VM 无法 kill 的问题时，触发此技能。关键词：Mac 内存检查、limactl 进程、kill PPID=1 进程、ollama 模型管理、launchd 服务、Colima 替代 Docker Desktop。"
metadata: {{ "openclaw": {{ "emoji": "🧠" }} }}
---

# Mac mini 内存优化与容器管理

本技能帮助你在 macOS（特别是 16GB 内存的 Mac mini）上排查和优化内存占用，清理冗余的 Docker Desktop 进程，管理 Ollama 模型，并确保 ClawBio 等工具正常运行。

## 适用场景

- macOS 系统内存紧张，需要排查占用来源
- Docker Desktop 占用过多内存，想用 Colima 替代
- 需要清理 Ollama 中不需要的模型
- Docker Desktop 的 Lima VM 进程（PPID=1）无法用普通 `kill` 命令终止
- 需要运行 ClawBio 的 methylation-clock 测试
- 想了解 Docker/Colima/Lima/容器的概念关系

## 步骤

### 1. 检查系统内存占用

```bash
ps aux --sort=-%mem | head -20
```

查看前 20 个内存占用最高的进程。关注：
- `limactl hostagent` — Lima VM 进程（Docker Desktop 或 Colima）
- `Virtualization.VirtualMachine` — macOS 虚拟化框架进程
- `ollama` — Ollama 服务和模型运行时

### 2. 区分 Docker Desktop 和 Colima 的 Lima VM

Docker Desktop 的 Lima VM 通常有两个 `limactl hostagent` 进程，各占 ~100MB。Colima 的 Lima VM 只有 `colima` daemon 进程 + 1 个 `limactl hostagent`。

### 3. 管理 Ollama 模型

```bash
# 列出所有模型
ollama list

# 删除指定模型（谨慎操作）
ollama rm 模型名称

# 重新拉取模型
ollama pull 模型名称
```

注意：删除前务必确认模型用途。典型保留场景：
- `bge-m3:567m` — MemOS 记忆系统用，向量嵌入
- `kimi-k2.5:cloud` — 云端模型，不占本地存储

### 4. 彻底终止 Docker Desktop 的 Lima VM 进程

Docker Desktop 的 Lima VM 由 launchd 托管（PPID=1），普通 `kill` 无效。

```bash
# 查看所有 Lima 相关进程
ps aux | grep limactl

# 普通 kill 无效，需用
sudo kill -9 <PID>

# 或者一次性清理所有 limactl 进程（需确认不是 Colima）
sudo pkill -9 limactl
```

**危险**：Colima 也用 limactl，误杀会导致 Docker 不可用。操作前用 `ps aux | grep limactl` 确认进程来源：

- `docker-desktop-linux` 开头的 → Docker Desktop ✅ 可杀
- `colima` 开头的 → Colima ❌ 保留

### 5. 重启 Colima（如误杀）

```bash
colima start
docker context use colima
```

### 6. 运行 ClawBio methylation-clock 测试

```bash
/Users/memou/.openclaw-agents/clawbio/venv/bin/python \
  /Users/memou/.openclaw-agents/clawbio/skills/epigenetic-age/run.py \
  --input /Users/memou/test_bio_sample.csv
```

成功标志：生成 `predictions.csv` 和时钟分布图。

## 常见问题与解决

❌ **普通 `kill <PID>` 无法终止 Docker Desktop VM 进程**  
→ 原因：这些进程 PPID=1，由 launchd 托管，普通信号被忽略  
✅ **解决**：使用 `sudo kill -9 <PID>` 强制终止

❌ **误把 Colima VM 当成 Docker Desktop 杀掉**  
→ 原因：两个服务都用 Lima，看到的 `limactl hostagent` 进程名字相似  
✅ **解决**：先 `ps aux | grep limactl` 看进程完整命令行，`colima` 开头的是 Colima。误杀后用 `colima start` 恢复

❌ **删除了不该删的 Ollama 模型（如 kimi-k2.5:cloud）**  
→ 原因：用户说"删掉某个模型"时没二次确认  
✅ **解决**：执行前再确认用户意图，特别是提到"云端"的模型通常不占本地但仍需要保留注册信息。删除后用 `ollama pull` 重新拉取

❌ **Colima 启动后 Docker 仍显示连接失败**  
→ 原因：Docker context 指向了 Docker Desktop  
✅ **解决**：执行 `docker context use colima`

## 核心概念

| 概念 | 说明 |
|------|------|
| **Lima** | macOS 上启动 Linux VM 的工具（开源项目），Docker Desktop 4.8+ 和 Colima 都基于它 |
| **Colima** | Lima 的轻量封装，专门为 macOS 无头环境设计，不带 GUI，占用 ~200MB |
| **Docker Desktop** | 带 GUI 的 Docker 桌面版，底层在 macOS 上也是 Lima VM，但额外跑管理 UI 服务，占用 ~2GB+ |
| **容器** | 打包应用 + 依赖的轻量虚拟环境 |
| **runc** | OCI 标准中真正创建容器的工具 |
| **containerd** | 容器生命周期管理（Docker 贡献给 CNCF） |

ClawBio 绝大多数分析（GWAS Lookup、ClinPGx、RNA-seq DE、甲基化时钟）直接在 Mac mini 本地运行 Python/R 脚本，**不需要 Docker 容器**，仅 Galaxy Bridge 等少数场景远程调用容器。

## 环境要求

- macOS Apple Silicon（Mac mini）
- 16GB RAM（优化目标：空闲从 260MB 提升到 4GB+）
- 已安装 Colima（Docker Desktop 可选）
- Ollama（用于本地 LLM 服务）
- Python 3.10+ 环境（ClawBio venv）

## 配套文件

如需自动化脚本：
- `scripts/cleanup-docker.sh` — 清理 Docker Desktop 进程并保留 Colima
- `scripts/check-memory.sh` — 快速检查内存占用前 15 名进程
```

## Companion files

- `references/ollama-models-guide.md` — reference documentation
- `references/colima-vm-tuning.md` — reference documentation
- `references/mac-memory-distribution.md` — reference documentation
- `references/docker-lima-colima-concepts.md` — reference documentation
- `references/launchd-pid1-process.md` — reference documentation
- `references/clawbio-methylation-clock.md` — reference documentation