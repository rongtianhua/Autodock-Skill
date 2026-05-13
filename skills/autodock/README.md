# AutoDock Skill — 分子对接自动化分析工具 / Molecular Docking Automation Toolkit

[![CI](https://github.com/rongtianhua/Autodock-Skill/actions/workflows/test.yml/badge.svg)](https://github.com/rongtianhua/Autodock-Skill/actions)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 中文介绍

**AutoDock Skill** 是一个面向发表级分子对接研究的自动化分析工具集，基于 [AutoDock Vina 1.2.5](https://vina.scripps.edu/) + [PLIP](https://github.com/pharmai/plip) + [RDKit](https://www.rdkit.org/) + [PyMOL](https://pymol.org/) 构建，支持从蛋白结构获取到相互作用可视化的全流程自动化。

### 核心功能

| 模块 | 功能 | 对标标准 |
|------|------|---------|
| 结构获取 | PDB / AlphaFold / CIF 多格式支持 | RCSB PDB API |
| 受体/配体制备 | PDBQT 自动转换、电荷计算 | AutoDock 官方协议 |
| 结合位点检测 | fpocket + P2Rank 双策略 | fpocket 论文 (Le Guillou 2011) |
| 分子对接 | Vina 采样，exhaustiveness=32 | CASF-2013 基准 |
| 相互作用分析 | PLIP 11 种相互作用类型全覆盖 | PLIP 官方文档 |
| 2D 可视化 | RDKit Cairo 渲染，300dpi | LigPlot+ v4.0 参数 |
| 3D 可视化 | PyMOL 场景渲染，Leipzig 虚线标准 | PyMOL 官方文档 |
| 结合自由能 | 简化 MM/GBSA + AmberTools MMPBSA.py | Miller et al. 2012 JCTC |
| 重对接验证 | Kabsch RMSD + MCS 回退 | CASF-2013 / PMC12661494 |
| 虚拟筛选 | SnakeMake 工作流，批量对接 | Snakemake 官方最佳实践 |

### 快速开始

```bash
# 1. 创建 conda 环境
conda env create -f environment.yml
conda activate autodock313

# 2. 检查依赖
python -m autodock status

# 3. 一键对接
python -m autodock run --receptor 6LU7 --ligand aspirin

# 4. 或分步执行
python -m autodock fetch pdb 6LU7
python -m autodock prepare-receptor 6LU7.pdb receptor.pdbqt
python -m autodock prepare-ligand aspirin ligand.pdbqt
python -m autodock dock receptor.pdbqt ligand.pdbqt --center 10 20 30 --box-size 20 20 20
```

### 环境要求

- **OS**: macOS (Apple Silicon) / Linux (x86_64/ARM64)
- **Python**: 3.11+
- **Conda**: Miniconda / Anaconda
- **核心依赖**: RDKit ≥2026.03.1, Vina ≥1.2.5, PyMOL ≥3.1.0, PLIP ≥2.3.0, Meeko ≥0.7.1, fpocket ≥4.2.3

### 项目结构

```
.
├── autodock/           # 核心模块
│   ├── _core.py        # 数据结构与公共工具
│   ├── _docking.py     # Vina 对接引擎
│   ├── _interactions.py # PLIP 相互作用检测
│   ├── _ligplot.py     # 2D 相互作用渲染
│   ├── _rendering_3d.py # PyMOL 3D 可视化
│   ├── _mmpbsa.py      # 简化 MM/PBSA
│   ├── _mmpbsa_amber.py # AmberTools MMPBSA.py 封装
│   ├── _preparation.py # 受体/配体制备
│   ├── _validation.py  # 重对接验证
│   └── ...
├── schemas/            # SnakeMake 配置校验 (Pydantic)
├── tests/              # 单元测试 (pytest)
├── Snakefile           # SnakeMake 工作流
├── environment.yml     # Conda 环境锁定
└── SKILL.md            # 完整 API 文档
```

### 发表级标准

本工具遵循以下发表标准：
- **采样深度**: CASF-2013 标准 (exhaustiveness=32)
- **验证协议**: RMSD < 2.0 Å (Kabsch + MCS 回退)
- **相互作用**: PLIP 11 种类型全覆盖，距离/角度阈值对齐官方默认值
- **可视化**: DPI 300, LigPlot+ v4.0 元素颜色/线宽/字体标准
- **可复现性**: 完整参数记录 (seed, center, box_size, exhaustiveness) + SnakeMake 工作流

### 作者与引用

**作者**: 戎天华 (Allen Rong) — 北京天坛医院骨科 / MiniMax 10x Team 研究员  
**联系**: rongtianhua@163.com

如使用本工具发表研究成果，请引用：
- AutoDock Vina: Eberhardt et al. (2021) J. Chem. Inf. Model. 61:3891-3898
- PLIP: Salentin et al. (2015) J. Chem. Inf. Model. 55:455-461
- fpocket: Le Guillou et al. (2011) BMC Bioinformatics 12:221

---

## English Introduction

**AutoDock Skill** is a publication-ready molecular docking automation toolkit built on [AutoDock Vina 1.2.5](https://vina.scripps.edu/) + [PLIP](https://github.com/pharmai/plip) + [RDKit](https://www.rdkit.org/) + [PyMOL](https://pymol.org/), supporting fully automated workflows from protein structure retrieval to interaction visualization.

### Core Features

| Module | Function | Reference Standard |
|--------|----------|-------------------|
| Structure Fetch | PDB / AlphaFold / CIF multi-format | RCSB PDB API |
| Receptor/Ligand Prep | PDBQT auto-conversion, charge calc | AutoDock official protocol |
| Pocket Detection | fpocket + P2Rank dual strategy | fpocket paper (Le Guillou 2011) |
| Docking | Vina sampling, exhaustiveness=32 | CASF-2013 benchmark |
| Interaction Analysis | All 11 PLIP interaction types | PLIP official docs |
| 2D Visualization | RDKit Cairo render, 300dpi | LigPlot+ v4.0 parameters |
| 3D Visualization | PyMOL scene render, Leipzig dash | PyMOL official docs |
| Binding Free Energy | Simplified MM/GBSA + AmberTools MMPBSA.py | Miller et al. 2012 JCTC |
| Redocking Validation | Kabsch RMSD + MCS fallback | CASF-2013 / PMC12661494 |
| Virtual Screening | SnakeMake workflow, batch docking | Snakemake best practices |

### Quick Start

```bash
# 1. Create conda environment
conda env create -f environment.yml
conda activate autodock313

# 2. Check dependencies
python -m autodock status

# 3. One-command docking
python -m autodock run --receptor 6LU7 --ligand aspirin

# 4. Or step by step
python -m autodock fetch pdb 6LU7
python -m autodock prepare-receptor 6LU7.pdb receptor.pdbqt
python -m autodock prepare-ligand aspirin ligand.pdbqt
python -m autodock dock receptor.pdbqt ligand.pdbqt --center 10 20 30 --box-size 20 20 20
```

### System Requirements

- **OS**: macOS (Apple Silicon) / Linux (x86_64/ARM64)
- **Python**: 3.11+
- **Conda**: Miniconda / Anaconda
- **Key Dependencies**: RDKit ≥2026.03.1, Vina ≥1.2.5, PyMOL ≥3.1.0, PLIP ≥2.3.0, Meeko ≥0.7.1, fpocket ≥4.2.3

### Project Structure

```
.
├── autodock/           # Core modules
│   ├── _core.py        # Data structures & utilities
│   ├── _docking.py     # Vina docking engine
│   ├── _interactions.py # PLIP interaction detection
│   ├── _ligplot.py     # 2D interaction rendering
│   ├── _rendering_3d.py # PyMOL 3D visualization
│   ├── _mmpbsa.py      # Simplified MM/PBSA
│   ├── _mmpbsa_amber.py # AmberTools MMPBSA.py wrapper
│   ├── _preparation.py # Receptor/ligand preparation
│   ├── _validation.py  # Redocking validation
│   └── ...
├── schemas/            # SnakeMake config validation (Pydantic)
├── tests/              # Unit tests (pytest)
├── Snakefile           # SnakeMake workflow
├── environment.yml     # Conda environment lock
└── SKILL.md            # Complete API documentation
```

### Publication Standards

This toolkit follows these publication standards:
- **Sampling Depth**: CASF-2013 standard (exhaustiveness=32)
- **Validation Protocol**: RMSD < 2.0 Å (Kabsch + MCS fallback)
- **Interactions**: Full 11-type PLIP coverage, distance/angle thresholds aligned with official defaults
- **Visualization**: DPI 300, LigPlot+ v4.0 element colors/line widths/font standards
- **Reproducibility**: Complete parameter logging (seed, center, box_size, exhaustiveness) + SnakeMake workflow

### Author & Citation

**Author**: Rong Tianhua (Allen Rong) — Beijing Tiantan Hospital Orthopedics / MiniMax 10x Team Researcher  
**Contact**: rongtianhua@163.com

If you use this toolkit in published research, please cite:
- AutoDock Vina: Eberhardt et al. (2021) J. Chem. Inf. Model. 61:3891-3898
- PLIP: Salentin et al. (2015) J. Chem. Inf. Model. 55:455-461
- fpocket: Le Guillou et al. (2011) BMC Bioinformatics 12:221

---

## License / 许可证

MIT License — 详见 [LICENSE](LICENSE) 文件。
