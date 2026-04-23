# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

## Bioinformatics Environment

### ClawBio — 生物信息学技能库
- **位置**: `~/.openclaw/clawbio/`
- **Python 路径**: `/Users/allenrong/Library/Python/3.14/lib/python/site-packages`
- **激活方式**: 每次运行 ClawBio 脚本前必须：
  ```python
  import sys
  sys.path.insert(0, '/Users/allenrong/Library/Python/3.14/lib/python/site-packages')
  sys.path.insert(0, '/Users/allenrong/.openclaw/clawbio')
  ```

### R + Bioconductor
- **R 版本**: 4.5.3 (Homebrew)
- **R 库路径**: `/opt/homebrew/lib/R/4.5/site-library/`
- **已装 Bioconductor 包**: DESeq2, SingleCellExperiment, scater, scran, ComplexHeatmap, SummarizedExperiment, GenomicRanges, rtracklayer, GenomicFeatures, VariantAnnotation, AnnotationHub ✅
- **安装命令**: `BiocManager::install('包名', ask=FALSE)`

### Docker（OrbStack 运行时）
- **运行时**: OrbStack 2.0.5（`brew install orbstack`）
- **Docker socket**: `~/.orbstack/run/docker.sock`（默认）
- **启动**: OrbStack 自动后台运行，无需手动启动
- **开机自启**: OrbStack 随系统启动
- **Docker 版本**: 29.0.4
- **当前 context**: `orbstack`
- **切换命令**: `docker context use orbstack` / `docker context use colima`
- **注意**: Colima 已删除；OrbStack 性能优于 Colima

### 已安装的 Python 包（bioinformatics）
```
biopython 1.87
scikit-learn 1.8.0
matplotlib 3.10.8
openai 2.32.0 (含 anndata, pydeseq2)
google-cloud-bigquery 3.41.0
```

### ClawBio 技能路由
详见 `~/.openclaw/workspace/skills/clawbio-wrapper/SKILL.md`

### Conda 科研环境（Miniconda base）
**Conda 路径**: `/opt/homebrew/Caskroom/miniconda/base/bin/conda`
**环境根目录**: `/opt/homebrew/Caskroom/miniconda/base/envs/`
**通用激活方式**（需先设置 PATH）:
```bash
# 基础 PATH（所有 conda 环境共享）
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/openjdk/bin:$PATH"

# 激活特定环境
conda activate <环境名>
# 或直接用完整路径
/opt/homebrew/Caskroom/miniconda/base/envs/<环境名>/bin/conda activate <环境名>
```

**⚠️ conda base 环境警告**: `zstandard` 被 conda 自己依赖，**禁止**在 base 环境中安装/删除任何包，否则会导致 conda 损坏。新工具一律建新环境。

#### 环境列表

| 环境名 | 大小 | 用途 | Python | 备注 |
|--------|------|------|--------|------|
| `rnaseq-pipeline` | 4.6 GB | 通用上游分析（原始数据→表达量矩阵） | 3.12 | 含 STAR/HISAT2/Bowtie2/kallisto/salmon/HTSeq/subread/MACS3/StringTie/Picard/BCFtools/bedtools/sra-tools/fastp/fastQC/cutadapt/trimmomatic/SeqKit/multiqc/delly/tobias 等 |
| `scvi` | 2.1 GB | 单细胞分析（scvi-tools） | — | scvi-tools + scanpy |
| `geneformer` | 1.6 GB | 单细胞 Geneformer | — | Geneformer 完整包 |
| `scgen` | 1.3 GB | 单细胞 scgen | — | scgen 2.1.0 + scvi 1.1.6 |
| `tobias` | 737 MB | ATAC-seq 足迹分析 | 3.12 | ATAC-seq 专用 |
| `pwas` | 507 MB | PWAS 分析 | — | — |
| `mdanalysis` | 419 MB | 分子动力学分析 | — | MDAnalysis |
| `deeptools` | 278 MB | ChIP-seq 深度分析 | — | deeptools |
| `autodock` | 120 MB | 分子对接 | — | AutoDock4/AutoDock-Vina |
| `scvi` | 2.1 GB | — | — | 同上 |

#### rnaseq-pipeline 环境工具清单（2026-04-21）
```
samtools 1.22.1      # BAM/SAM 处理
bcftools 1.22        # 变异 calling
blastn 2.16.0+        # 序列比对
minimap2 2.30        # 长序列比对
bedtools 2.31.1      # 基因组操作
fastp 1.1.0          # 过滤/去接头
kraken2 2.17.1       # 物种注释
metaphlan 4.0.6      # 宏基因组
sra-tools 3.4.1      # SRA 数据下载（fastq-dump, prefetch）
bwa-mem2 2.2.1      # 基因组比对
bowtie2 2.5.5        # 短序列比对
STAR 2.7.11b         # RNA-seq 比对
HISAT2 2.2.2         # SNP/剪接感知比对
MACS3 3.0.4          # Peak calling
StringTie 3.0.3      # 转录本组装
subread 2.1.1        # 计数/覆盖度
HTSeq 2.1.2          # 计数定量
kallisto 0.52.0      # 伪比对定量
salmon 1.10.3        # 伪比对定量
multiqc 1.33         # QC 汇总
FastQC 0.12.1        # 原始数据 QC
cutadapt 5.2          # 接头去除
trimmomatic 0.40     # 滑动窗口修剪
SeqKit 2.13.0        # 序列处理
Picard 3.4.0         # 标记重复/QC
delly v1.7.2         # 结构变异检测
tobias 0.17.3        # ATAC-seq 足迹分析
cnvkit 0.9.10        # CNV 分析（pip 安装）
```
**Java 依赖工具**（需设置 JAVA_HOME）:
```bash
export JAVA_HOME="/opt/homebrew/Caskroom/miniconda/base/envs/rnaseq-pipeline/lib/jvm"
# Picard、trimmomatic、qualimap 需要此设置
```

#### 散装工具（不在 conda 环境内）
| 工具 | 安装方式 | 备注 |
|------|---------|------|
| **Manta** | Docker `dceoy/manta:latest` | 结构变异检测；conda 版本与 Python 3.12 冲突 |
| **CNVkit** | Docker `etal/cnvkit:latest` | CNV 分析；conda 版本 pandas 兼容性问题，通过 Docker 解决 |

### Docker 镜像（Bioinformatics）
| 镜像 | 大小 | 用途 | 状态 |
|------|------|------|------|
| `kenjikamimoto126/celloracle_ubuntu` | 11.2 GB | CellOracle 单细胞网络推断 | ✅ |
| `opoirion/celloracle` | 3.26 GB | CellOracle | ✅ |
| `etal/cnvkit` | 3.73 GB | CNV 分析 | ✅ |
| `mgibio/homer` | 1.47 GB | ChIP-seq/ATAC-seq 注释 | ✅ |
| `brianyee/idr` | 1.25 GB | IDR 重复性分析 | ✅ |
| `openeuler/busco` | 641 MB | 保守基因评估（BUSCO） | ✅ |
| `dceoy/manta` | 484 MB | 结构变异检测 | ✅ |
| `ubuntu` | 69.6 MB | 基础镜像 | ✅ |

**Docker 通用命令**:
```bash
# 拉取镜像
docker pull <镜像名>

# 运行交互式容器
docker run --rm -it <镜像名> /bin/bash

# 直接运行命令（替代本地安装）
docker run --rm <镜像名> <命令> <参数>

# Manta 使用示例
docker run --rm dceoy/manta configManta.py --help

# CNVkit 使用示例
docker run --rm etal/cnvkit cnvkit.py batch --help
```

### R + Bioconductor
- **R 版本**: 4.5.3 (Homebrew)
- **R 库路径**: `/opt/homebrew/lib/R/4.5/site-library/`
- **已装 Bioconductor 包**: DESeq2, SingleCellExperiment, scater, scran, ComplexHeatmap, SummarizedExperiment, GenomicRanges, rtracklayer, GenomicFeatures, VariantAnnotation, AnnotationHub ✅
- **安装命令**: `BiocManager::install('包名', ask=FALSE)`

### Demo 测试状态（2026-04-18）
| 技能 | 状态 |
|------|------|
| gwas-lookup | ✅ |
| clinpgx | ✅ |
| fine-mapping | ✅ |
| rnaseq-de | ✅ |
| galaxy-bridge | ✅ |
| methylation-clock | ✅ (pyaging 0.1.30 环境已就绪) |

### methylation-clock（pyaging 环境）
- **Python 环境**: Miniconda Python 3.13（`~/miniconda3/envs/pyaging/`）
- **运行方式**: `~/miniconda3/envs/pyaging/bin/python` 或 `source ~/miniconda3/etc/profile.d/conda.sh && conda activate pyaging`
- **pyaging 版本**: 0.1.30 ✅ 已安装

### MemOS 本地记忆系统
- **性质**: OpenClaw Node.js 插件（TypeScript）
- **插件路径**: `~/.openclaw/extensions/memos-local-openclaw-plugin/`
- **版本**: 1.0.8
- **功能**: 混合检索（RRF + MMR + 时序）、任务摘要、技能演化、团队共享
- **Viewer**: http://localhost:18799（Gateway 内置端口）
- **记忆文件**: `~/.openclaw/workspace/memory/*.md`（60+ 条）
- **Dreaming Cron**: 见下方「Cron 任务」章节
- **用途**: 对话级记忆，快速检索，短期上下文

### Evolver 自我进化引擎
- **性质**: Node.js 进程 + EvoMap Hub 云服务
- **进程**: `node /opt/homebrew/lib/node_modules/@evomap/evolver/index.js --loop`
- **管理**: LaunchAgent `ai.openclaw.evolver`（`~/.openclaw/workspace/skills/evolver/start.sh`）
- **A2A Node ID**: `EVM-FREE-E3D3F868-C50E`
- **A2A Hub**: `https://evomap.ai`
- **日志**: `/tmp/evolver-proxy.log`
- **Cron**: 自我扫描（无 cron，靠 loop 驱动）
- **用途**: 分析会话历史，识别错误和低效，触发进化提案

### OpenSpace 技能搜索与执行引擎（HKUDS）
- **性质**: Python MCP Server + Dashboard API
- **源码**: `~/.openclaw/workspace/OpenSpace/`
- **MCP Server**: `ai.openclaw.openspace-mcp` → port 8081（streamable-http）
- **Dashboard API**: `ai.openclaw.openspace-dashboard` → port 7788
- **前端**: Vite dev server → port 3789（需手动 `npm run dev`）
- **Conda 环境**: `openspace`（`/opt/homebrew/Caskroom/miniconda/base/envs/openspace/`）
- **扫描路径**: `~/.openclaw/workspace/skills/`（不含 `~/.openclaw/skills/` bioskills）
- **LaunchAgent**:
  - `ai.openclaw.openspace-mcp.plist`（port 8081）
  - `ai.openclaw.openspace-dashboard.plist`（port 7788）

### Hindsight 长期记忆系统
- **性质**: Docker 容器（OrbStack）
- **镜像**: `ghcr.io/vectorize-io/hindsight:latest`（4.15GB）
- **容器名**: `hindsight`
- **Restart Policy**: `unless-stopped`（重建后已修复）
- **API 端点**: http://localhost:8888
- **Control Plane**: http://localhost:9999（Next.js Web UI）
- **Bank**: `openclaw-main`
- **LLM Provider**: `minimax`（CN 端点 `api.minimaxi.com/v1`）
- **LLM Model**: `MiniMax-M2.7`
- **环境变量**（已备份至 `~/.openclaw/hindsight-env.sh`）:
  ```
  HINDSIGHT_API_LLM_PROVIDER=minimax
  HINDSIGHT_API_LLM_BASE_URL=https://api.minimaxi.com/v1
  HINDSIGHT_API_LLM_MODEL=MiniMax-M2.7
  HINDSIGHT_API_LLM_API_KEY=sk-cp-...
  HINDSIGHT_API_PORT=8888
  HINDSIGHT_CP_DATAPLANE_API_URL=http://localhost:8888
  HINDSIGHT_ENABLE_API=true
  HINDSIGHT_ENABLE_CP=true
  ```
- **集成脚本**: `~/.openclaw/workspace/skills/hindsight/hook.sh`
- **调用**: `retain`/`recall`/`reflect`/`status`
- **与 MemOS 分工**: MemOS 管快速对话检索，Hindsight 管长期学习+观察体合并

### Cron 任务（OpenClaw）

| ID | 名称 | 时间 | 投递通道 | 状态 |
|----|------|------|---------|------|
| `76b1a405...` | MemOS Dreaming | 每天 03:00 | feishu → ou_fd31b5e8e4caee8de4729f302cda0034 | idle |
| `c7f9196d...` | MemOS Dreaming Audit | 每周六 10:00 | feishu → ou_fd31b5e8e4caee8de4729f302cda0034 | idle |
| `1cf8b8eb...` | a-stock-trader-pro 开盘 | 周一至五 09:35 | openclaw-weixin → c34be62a65ea-im-bot | idle |
| `e421ef30...` | 智谱 Coding Plan 提醒 | 每天 09:50 | feishu → ou_fd31b5e8e4caee8de4729f302cda0034 | idle |
| `02cc6244...` | Biblium/Litstudy 提醒 | 每天 10:00 | feishu → ou_fd31b5e8e4caee8de4729f302cda0034 | idle |
| `c3fe07a7...` | openclaw-config-backup | 每 3 天 | isolated → main | ok |
| `c5e086a7...` | OpenClaw Log Rotation | 每周日 03:00 | isolated | ok |

**投递字段规范**（经验教训，严格遵守）:
- `mode`: `announce`（非 `none`）
- `channel`: `feishu` 或 `openclaw-weixin`
- `to`: 目标用户 ID

### 四大系统迁移检查清单

**迁移主机时，按以下顺序检查：**

1. **MemOS**: 迁移 `~/.openclaw/extensions/memos-local-openclaw-plugin/` + `~/.openclaw/workspace/memory/`
2. **Evolver**: 迁移 `~/.openclaw/workspace/skills/evolver/start.sh`（重建 LaunchAgent）
3. **OpenSpace**: 迁移 `~/.openclaw/workspace/OpenSpace/` + conda env `openspace`（重建 LaunchAgent）
4. **Hindsight**: 重建 Docker 容器（使用 `~/.openclaw/hindsight-env.sh` 中的环境变量）
5. **Cron**: 用 `openclaw cron list` 导出所有任务配置，重建
6. **Gateway**: 迁移 `~/.openclaw/openclaw.json`

