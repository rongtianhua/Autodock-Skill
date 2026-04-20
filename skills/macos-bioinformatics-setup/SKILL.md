---

# macOS Apple Silicon 生物信息学环境全量配置

在 Mac mini (Apple Silicon) 上从零搭建完整的生信分析环境，涵盖 conda 工具链、Docker 容器化工具、R 语言发表级分析包，以及多框架（bioSkills、ClawBio）的协同配置。

## 何时使用此技能

- 新 Mac 配置生信环境，不知道从哪里开始
- conda 安装工具时遇到 osx-arm64 依赖冲突（sepp、augustus、perl 等）
- 系统里有多个 conda 环境，不知道哪个是主力
- 某些 conda 包装不上（如 cnvkit、manta、tobias），需要 Docker 方案
- 想用 Docker 但不知道如何为生信工具创建快捷命令
- R 包安装遇到 Java 相关依赖问题
- 需要安装发表级 Python 可视化包（pingouin、lifelines 等）

## 步骤

### 1. 确认唯一的 Miniconda 路径

```bash
which conda
# 确认路径指向 /opt/homebrew/bin/conda（Caskroom 版）
# 不要有多套 ~/miniconda3 与 Caskroom 版本共存
```

如果有残留的 `~/miniconda3/`，安全删除：

```bash
rm -rf ~/miniconda3
```

**为什么需要关注路径：** macOS 上通过 Homebrew `--cask` 安装的 Miniconda 放在 `/opt/homebrew/Caskroom/miniconda/base/`，软链接到 `/opt/homebrew/bin/conda`。如果同时存在用户手动安装的版本（通常在 `~/miniconda3/`），两套 pkgs 目录会互相干扰，且 `conda list` 查到的内容容易混淆。清理后只保留 Caskroom 版本即可。

### 2. 配置 .condarc（strict channel priority）

```yaml
channels:
  - conda-forge
  - bioconda
  - defaults
channel_priority: strict
auto_update_conda: false
```

```bash
conda config --set channel_priority strict
conda config --set auto_update_conda false
```

**为什么 strict 优先：** 避免 conda-forge 和 defaults 混合时出现版本冲突，strict 模式下按 channel 优先级严格锁定，兼容性问题更容易发现。

### 3. 初始化 conda 并关闭 base 自动激活

```bash
conda init zsh
conda config --set auto_activate_base false
```

**为什么关闭 auto_activate_base：** base 环境始终激活会拖慢 shell 启动速度，且与手动管理的专用环境冲突。按需 `conda activate` 是更好的做法。

### 4. 安装核心生信工具（mamba 加速）

```bash
# 先装 mamba 加速后续安装
conda install -n base -c conda-forge mamba

# 核心工具（分批安装，避免内存溢出）
mamba install -c conda-forge -c bioconda \
  samtools bcftools bedtools bowtie2 STAR hisat2 salmon \
  fastqc mafft muscle trimmomatic picard multiqc blast+ \
  fastp minimap2 sra-tools bwa-mem2 kraken2 metaphlan delly macs3
```

**为什么用 mamba：** mamba 是 conda 的 Rust 重写版，并行求解依赖，速度比 conda 快 10-20 倍。在安装大量包时优势明显。

### 5. Docker 工具补齐（conda 无法安装的部分）

**BUSCO：**
```bash
# 优先查找 arm64 原生镜像
docker run --rm openeuler/busco:5.8.3-oe2403sp1 busco --version

# 创建快捷命令 ~/bin/busco
cat > ~/bin/busco << 'EOF'
#!/bin/zsh
docker run --rm -v "$(pwd):/data" \
  openeuler/bosco:5.8.3-oe2403sp1 "$@"
EOF
chmod +x ~/bin/busco
```

**cnvkit / manta / homer / idr：**
```bash
docker pull etal/cnvkit:latest
docker pull dceoy/manta:latest
docker pull mgibio/homer
docker pull brianyee/idr:latest

# 创建快捷脚本 ~/bin/cnvkit.py、~/bin/manta、~/bin/homer、~/bin/idr
```

**为什么用 Docker 补齐：** cnvkit（pandas API 变更）、manta（bioconda 无 osx-arm64 构建）、tobias（Python 3.13 不兼容）等在 conda 上无法直接解决。Docker 容器化运行既绕过依赖地狱，又不污染宿主机环境。Apple Silicon 上优先找 arm64 原生镜像，次选 amd64 + OrbStack Rosetta2 转译。

### 6. conda 隔离环境（处理 Python 版本冲突）

```bash
# tobias 需要 Python 3.9-3.12
conda create -n tobias python=3.12
conda activate tobias
mamba install -c bioconda tobias

# deeptools 独立环境
conda create -n deeptools python=3.12
conda activate deeptools
mamba install -c conda-forge deeptools pybigwig
```

**为什么隔离：** 某些工具对 Python 版本有硬性要求（如 tobias 不支持 3.13），与其他工具的 Python 版本要求冲突时，创建独立 conda 环境是标准解法。

### 7. 发表级 Python 包

```bash
conda activate base
mamba install -c conda-forge \
  pingouin lifelines adjustText tabulate bioinfokit dataframe_image
```

**包的作用：**
- `pingouin` — 方差分析、效应量、相关性
- `lifelines` — Kaplan-Meier 曲线、Cox 比例风险模型
- `adjustText` — 防止散点图标签重叠
- `bioinfokit` — 热图、PCA、聚类（生信专用）
- `dataframe_image` — DataFrame 导出为图片

### 8. R 包（conda r-base 环境）

```bash
# 可视化
install.packages(c(
  "ggplot2", "ggpubr", "survminer", "ggsignif", "ggfortify",
  "patchwork", "GGally", "UpSetR"
))

# 表格与报告
install.packages(c(
  "gt", "gtsummary", "flextable", "tableone", "janitor"
))
```

**如果遇到 rJava 安装失败：** 先通过 Homebrew 安装 OpenJDK，`brew install openjdk`，然后 `R CMD javareconf` 刷新 R 的 Java 配置，再重新安装 rJava。

### 9. OrbStack 配置（替代 Docker Desktop）

```bash
# 确认 OrbStack 运行且 Docker context 正确
docker context ls
# 应该看到 orbstack 设为 active

# 如果 context 不对，切过来
docker context use orbstack
```

**为什么用 OrbStack：** Apple Silicon 专用，内存占用低，启动快，与 Colima/Docker Desktop 相比针对 macOS Virtualization.framework 做了优化，适合长期运行的服务器环境。

## 陷阱与解决方案

❌ **conda 安装 BUSCO 报错（sepp/augustus/perl 依赖冲突）**
→ 改用 Docker 镜像。先找 arm64 原生镜像（`openeuler/busco`），找不到再用 amd64 镜像（`ezlabgva/busco`），OrbStack 会通过 Rosetta2 自动转译，不影响功能。

❌ **conda list 看不到已安装的工具，但 which 能找到**
→ 系统有多套 Miniconda（Homebrew Caskroom 版 + 用户手动版）。清理 `~/miniconda3/`，只用 Caskroom 那套。删除后 `which conda` 应指向 `/opt/homebrew/bin/conda`。

❌ **飞书/微信等会话上下文溢出，消息无法回复**
→ 对应的会话历史积累过多 token。对会话执行 compaction（压缩历史行数），保留系统提示词和最近 30 条即可。定期开新会话可预防。

❌ **tobias 报错 Python 3.13 不兼容**
→ 创建 Python 3.12 的隔离 conda 环境 `conda create -n tobias python=3.12`，在该环境中安装。

❌ **cnvkit 报错 pandas API 变更（Int64Index 被移除）**
→ 工具版本太老。改用 Docker 镜像 `etal/cnvkit:latest`，绕过 conda 包的版本问题。

❌ **proplot 安装失败（与 matplotlib 3.10 不兼容）**
→ 暂时跳过 proplot，继续用标准 matplotlib + seaborn 组合做图。proplot 的功能可以用其他方式实现（如 manim）。

❌ **scikitplot 安装失败（scipy 1.16 API 变更）**
→ 暂不安装。曲线绘制功能改用 matplotlib 手写或 scikit-learn + ownplot 代码。

❌ **R rJava 安装失败**
→ 先 `brew install openjdk` 再 `R CMD javareconf` 刷新 Java 配置。

## 关键配置

**.condarc（~/.condarc）：**
```yaml
channels:
  - conda-forge
  - bioconda
  - defaults
channel_priority: strict
auto_update_conda: false
```

**快捷命令示例（~/bin/busco）：**
```bash
#!/bin/zsh
docker run --rm -v "$(pwd):/data" \
  openeuler/busco:5.8.3-oe2403sp1 "$@"
```

## 环境与前提

- macOS Apple Silicon（M1/M2/M3/M4）
- OrbStack 或 Colima 已运行
- Homebrew 已安装
- RAM 建议 16GB+（否则分批安装，避开 SIGKILL）
- 网络畅通（conda/mamba 需下载大量包）

## 伴侣文件

- `scripts/busco` — BUSCO Docker 快捷命令
- `scripts/cnvkit.py` — CNVKit Docker 快捷命令
- `scripts/manta` — Manta Docker 快捷命令
- `scripts/homer` — Homer Docker 快捷命令
- `scripts/idr` — IDR Docker 快捷命令
```