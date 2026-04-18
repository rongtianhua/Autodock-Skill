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

### Docker（Colima 运行时）
- **运行时**: Colima（`brew install colima`）
- **Docker socket**: `~/.colima/docker/docker.sock`
- **启动**: `colima start --runtime docker`
- **开机自启**: `brew services start colima`（已配置）
- **Docker 版本**: 29.4.0
- **当前 context**: `colima`
- **注意**: Docker Desktop（`/Applications/Docker.app`）因无显示器无法运行，已停用

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
