# Docker / Colima / Lima / 容器概念关系

## 概念层次

```
┌─────────────────────────────────────────────────┐
│              Docker CLI / 用户界面              │
├─────────────────────────────────────────────────┤
│         Docker Engine / containerd               │
├─────────────────────────────────────────────────┤
│              runc (创建容器)                     │
├─────────────────────────────────────────────────┤
│           Linux VM (Lima / 虚拟化层)             │
├─────────────────────────────────────────────────┤
│         macOS / Apple Silicon 硬件               │
└─────────────────────────────────────────────────┘
```


## 组件说明

### 容器（Container）
轻量级虚拟环境，打包应用 + 全部依赖，确保跨平台一致性。

### runc
OCI 标准中**真正创建容器**的工具（底层）。

### containerd
容器**生命周期管理**工具，Docker 贡献给 CNCF 的项目。

### Lima
macOS 上启动 Linux VM 的**开源工具**，Docker Desktop 4.8+ 和 Colima 都基于它。

### Docker Desktop
带 GUI 的 Docker 桌面版：
- 底层也是 Lima VM
- 额外跑管理 UI 服务
- 占用 **2GB+** 内存

### Colima
Lima 的**轻量封装**，专为 macOS 无头环境设计：
- 不带 GUI
- 占用 **~200MB** 内存
- 适合服务器/CI 场景

## ClawBio 与 Docker 的关系


| 分析类型 | 是否需要 Docker |
|----------|----------------|
| GWAS Lookup | ❌ 不需要（本地 Python）|
| ClinPGx | ❌ 不需要（本地 R）|
| RNA-seq DE | ❌ 不需要（本地 Python）|
| 甲基化时钟 | ❌ 不需要（本地 Python）|
| Galaxy Bridge | ✅ 远程调用容器 |

**结论**：ClawBio 绝大多数分析直接在 Mac mini 本地运行 Python/R 脚本，**不需要 Docker 容器**。只有 Galaxy Bridge 等少数场景需要远程容器。
