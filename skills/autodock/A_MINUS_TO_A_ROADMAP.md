# Autodock 技能 — A- → A 冲击优化方案

**制定日期：** 2026-05-08  
**当前评分：** 84/100 (A-)  
**目标评分：** 90/100 (A)  
**差距：** +6分  

---

## 一、当前状态诊断

### 已修复项（P0/P1 + 进阶）
| 批次 | 内容 | 状态 |
|------|------|------|
| P0 | CI/CD (Pre-commit Hook) | ✅ |
| P0 | 统一异常体系 | ✅ |
| P0 | MM/PBSA精度声明 | ✅ |
| P1 | 类型注解 | ✅ |
| P1 | 2D距离标注 | ✅ |
| P1 | 多配体叠加 | ✅ |
| 进阶 | AmberTools MM/PBSA | ✅ |
| 进阶 | SnakeMake工作流 | ✅ |

### 本次审查新发现问题

| # | 问题 | 位置 | 严重程度 | 类型 |
|---|------|------|---------|------|
| 1 | 重复 import 块 | `_core.py` | 🔴 高 | 代码质量 |
| 2 | print() 未替换为 logging | `_database.py` | 🟡 中 | 代码质量 |
| 3 | print() 未替换为 logging | `_workflow_report.py` | 🟡 中 | 代码质量 |
| 4 | 异常体系未在捕获中使用 | `_structure_fetch.py` | 🟡 中 | 健壮性 |
| 5 | 异常体系未在捕获中使用 | `_database.py` | 🟡 中 | 健壮性 |
| 6 | `_autodock.py` 死代码/重复 | 根目录 | 🟡 中 | 代码质量 |
| 7 | `_patch_p0.py` 临时文件残留 | 根目录 | 🟡 中 | 清理 |
| 8 | 无抽象基类 | 核心接口 | 🟡 中 | 架构 |
| 9 | 配置分散无中心管理 | 多模块 | 🟡 中 | 架构 |
| 10 | 测试未覆盖 ADMET/Clustering | `tests/` | 🟡 中 | 测试 |
| 11 | `_ligplot.py` 文档缺失 | 根目录 | ⚠️ 低 | 文档 |
| 12 | `_admet.py` 测试缺失 | 根目录 | ⚠️ 低 | 测试 |

**问题 1 已修复：** `_core.py` 重复 import 块已清理 ✅

---

## 二、差距分析：A- (84) → A (90)

### 各维度得分与提升空间

| 维度 | 当前 | 目标 | 提升空间 | 优先级 |
|------|------|------|---------|--------|
| 代码稳健性 | 18/20 | 19/20 | +1 | 🔴 高 |
| 发表级可视化 | 18/20 | 19/20 | +1 | 🟡 中 |
| 科学流程 | 18/20 | 19/20 | +1 | 🟡 中 |
| 自动化程度 | 15/15 | 15/15 | 0 | — |
| 测试与文档 | 15/15 | 15/15 | 0 | — |
| **总分** | **84** | **90** | **+6** | **需要3个+1** |

### 关键瓶颈

要达到 90/100 (A)，需要在 **3 个维度** 各再提升 1 分：

1. **代码稳健性 18→19**：清理所有 print()、消除重复代码、统一错误处理
2. **发表级可视化 18→19**：增加药效团检测、多配体叠加对齐、距离标尺
3. **科学流程 18→19**：OpenMM 1ns 稳定性验证、或构象系综采样

---

## 三、优化方案（分 3 批次）

### 🔴 批次 Q0：代码质量根治（2小时，代码稳健性 +1）

**目标：** 消除所有技术债，代码达到生产级标准

#### Q0-1：清理 print() 语句 → logging（30min）

**文件：** `_database.py`, `_workflow_report.py`

**操作：**
```python
# _database.py 修改示例
# 替换前：
print(f"[autodock] Enrichment error: {stats['error']}")

# 替换后：
autodock_logger.error(f"Enrichment error: {stats['error']}")
```

**范围：**
- `_database.py`: 8 处 print → logging
- `_workflow_report.py`: 2 处 print → logging

#### Q0-2：删除死代码和临时文件（20min）

**操作：**
```bash
# 检查 _autodock.py 是否仍在被使用
grep -rn "_autodock" --include="*.py" . | grep -v "_autodock.py"

# 检查 _patch_p0.py 是否仍在被使用
grep -rn "_patch_p0" --include="*.py" .

# 如果无引用，标记为 deprecated 或删除
```

**决策：**
- `_autodock.py`: 检查是否被 `_docking.py` 导入，如果是，保留并标记 `__all__`
- `_patch_p0.py`: 确认为临时修复，删除
- `../AutoFigure` submodule: 检查状态，更新或移除

#### Q0-3：异常体系全面应用（40min）

**文件：** `_structure_fetch.py`, `_database.py`, `_preparation.py`

**操作：**
```python
# _structure_fetch.py 修改示例
# 替换前：
try:
    response = requests.get(url)
except Exception as e:
    raise RuntimeError(f"Fetch failed: {e}")

# 替换后：
try:
    response = requests.get(url)
except requests.RequestException as e:
    raise StructureFetchError(f"Failed to fetch {url}: {e}") from e
```

**范围：**
- `_structure_fetch.py`: 网络错误 → StructureFetchError
- `_database.py`: 数据库查询错误 → DataSourceError
- `_preparation.py`: 制备失败 → PreparationError
- `_validation.py`: 验证失败 → ValidationError

#### Q0-4：_core.py import 清理确认（10min）

**已修复 ✅：** 删除重复 import 块

**验证：** `conda run -n autodock313 pytest tests/ -m "not slow" -q`

---

### 🟡 批次 Q1：可视化与科学深度（4小时，可视化 +1，科学 +1）

#### Q1-1：药效团检测模块（2小时）

**新文件：** `_pharmacophore.py`

**功能：**
```python
def detect_pharmacophore(
    receptor_pdb: str,
    ligand_pdbqt: str,
    center: tuple,
    distance: float = 5.0,
) -> list[dict]:
    """
    Detect structure-based pharmacophore features from protein-ligand complex.
    
    Returns features:
    - H-bond donor (D)
    - H-bond acceptor (A)
    - Hydrophobic (H)
    - Aromatic (R)
    - Positive ionizable (P)
    - Negative ionizable (N)
    
    Each feature: {'type', 'center', 'atoms', 'radius'}
    """
```

**实现：**
- 使用 RDKit 的 `rdMolChemicalFeatures` 或自定义几何检测
- 基于口袋残基原子类型和位置
- 生成 Pharmacophore Query 文件 (.json/.pml)

**用途：**
- 虚拟筛选的药效团过滤
- 论文 Figure：口袋药效团特征标注
- 指导配体优化

#### Q1-2：OpenMM 1ns 稳定性验证（2小时）

**新文件：** `_md_validation.py`

**功能：**
```python
def validate_pose_stability(
    receptor_pdb: str,
    ligand_pdbqt: str,
    protocol: str = 'quick',  # 'quick' | 'short'
    output_dir: str = None,
) -> dict:
    """
    Validate docking pose stability via OpenMM molecular dynamics.
    
    Protocols:
    - 'quick': Energy minimization + 1ps NVT (5-10 min)
      Checks: no major clash, interaction retention > 80%
    
    - 'short': Minimization + 1ns NVT (30-60 min)
      Checks: ligand RMSD < 2Å, pocket RMSD < 1Å, 
              interaction retention > 60%
    
    Returns:
    {
        'is_stable': bool,
        'ligand_rmsd': float,      # Å (last 50% vs first frame)
        'pocket_rmsd': float,      # Å
        'interaction_retention': float,  # 0-1
        'minimized_pose': str,     # path to minimized PDBQT
        'trajectory': str | None,  # path to trajectory (short only)
    }
    """
```

**实现要点：**
- 使用 OpenMM Python API（已安装到 autodock-amber 环境）
- 轻量级：只验证结合稳定性，不做完整热力学分析
- 自动检测 GPU（Apple Metal），fallback CPU
- 对接 pose 作为初始结构，自动添加溶剂和离子

**集成到 DockingResult：**
```python
# dock_ligand() 新增参数
validate_stability: bool = False  # 默认关闭（耗时）

# DockingResult 新增字段
pose_stable: bool | None = None
stability_rmsd: float | None = None
```

---

### 🟢 批次 Q2：架构升级（4小时，可选，冲击 A+）

#### Q2-1：抽象基类（2小时）

**新文件：** `_abc.py`

```python
from abc import ABC, abstractmethod

class DockingEngine(ABC):
    """Abstract base for molecular docking engines."""
    
    @abstractmethod
    def dock(self, receptor, ligand, center, box_size) -> DockingResult:
        pass
    
    @abstractmethod
    def validate_protocol(self, receptor, ligand, center, box_size) -> dict:
        pass

class InteractionDetector(ABC):
    """Abstract base for interaction detection."""
    
    @abstractmethod
    def detect(self, receptor, ligand, center) -> list[dict]:
        pass

class StructureRenderer(ABC):
    """Abstract base for molecular rendering."""
    
    @abstractmethod
    def render(self, scene_config) -> str:
        pass
```

**现有类适配：**
- `VinaEngine(DockingEngine)` — 包装 `dock_ligand()`
- `PLIPDetector(InteractionDetector)` — 包装 `detect_interactions_plip()`
- `PyMOLRenderer(StructureRenderer)` — 包装 `render_scene()`

#### Q2-2：中央配置管理（2小时）

**新文件：** `_config.py`

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class AutodockConfig:
    """Centralized configuration for autodock skill."""
    
    # Paths
    cache_dir: Path = Path.home() / ".openclaw" / "structures_cache"
    log_dir: Path = Path.home() / ".openclaw" / "logs"
    tmp_dir: Path = Path.home() / ".openclaw" / "tmp"
    
    # Amber
    amber_env: str = "autodock-amber"
    amber_protocol_default: str = "quick"
    
    # Docking defaults
    default_exhaustiveness: int = 32
    default_n_poses: int = 10
    default_box_size: tuple = (20, 20, 20)
    
    # Force fields
    protein_forcefield: str = "ff14SB"
    ligand_forcefield: str = "gaff2"
    water_model: str = "tip3p"
    
    # Quality thresholds
    clash_threshold: float = 1.2  # Å (explicit-H)
    rmsd_redocking_threshold: float = 2.0  # Å
    stability_rmsd_threshold: float = 2.0  # Å
    
    # Visualization
    default_dpi: int = 300
    default_width: int = 2400
    default_height: int = 1800
    
    @classmethod
    def from_yaml(cls, path: str) -> "AutodockConfig":
        ...
    
    @classmethod
    def from_env(cls) -> "AutodockConfig":
        ...
```

---

## 四、实施路线图

```
Day 1 (2小时): Q0 批次 — 代码质量根治
    ├── Q0-1: print() → logging (30min)
    ├── Q0-2: 死代码清理 (20min)
    ├── Q0-3: 异常体系全面应用 (40min)
    └── Q0-4: 验证测试通过 (30min)

Day 2 (2小时): Q1-1 — 药效团检测
    ├── 实现 _pharmacophore.py (1.5h)
    ├── 测试 + 文档 (30min)

Day 3 (2小时): Q1-2 — OpenMM 稳定性验证
    ├── 实现 _md_validation.py (1.5h)
    ├── 测试 + 文档 (30min)

Day 4 (可选, 4小时): Q2 批次 — 架构升级
    ├── Q2-1: 抽象基类 (2h)
    └── Q2-2: 中央配置 (2h)
```

---

## 五、预期评分变化

| 批次 | 代码稳健性 | 可视化 | 科学流程 | 总分 |
|------|-----------|--------|---------|------|
| 当前 (A-) | 18 | 18 | 18 | **84** |
| + Q0 | **19** | 18 | 18 | **85** |
| + Q1-1 | 19 | **19** | 18 | **86** |
| + Q1-2 | 19 | 19 | **19** | **87** |
| + Q2 (可选) | **20** | **20** | **20** | **90** |

**结论：**
- **执行 Q0 + Q1 = 87/100 (接近 A)**
- **执行 Q0 + Q1 + Q2 = 90/100 (A)**

---

## 六、关键决策

### 决策 1：Q2 架构升级是否必要？

**我的建议：延后。**

理由：
1. 抽象基类和中央配置对**个人科研**边际收益低
2. 引入 ABC 会增加代码复杂度，对当前 14K 行代码的维护成本上升
3. Q0 + Q1 已达到 87 分，足以应对 Nature Communications/PNAS 级别
4. 只有在计划**开源发布**或**多人协作**时，Q2 才有必要

### 决策 2：OpenMM 验证用哪种协议？

**我的建议：只做 quick 协议（1ps NVT）。**

理由：
1. `quick`（5-10分钟）：能量最小化 + 1ps NVT，验证无 clash + 相互作用保留
2. `short`（30-60分钟）：1ns NVT，对顶刊才需要
3. 个人科研用 `quick` 足够筛选不稳定 pose
4. `short` 标记为"experimental"，用户显式启用

### 决策 3：药效团检测是否值得？

**我的建议：值得实施（2小时投入，显著提升论文质量）。**

理由：
1. 药效团是 docking 论文的**标准 Figure**
2. RDKit 有现成的 `rdMolChemicalFeatures`，实现成本低
3. 可直接用于虚拟筛选过滤（retain 有药效团匹配的化合物）
4. 2 小时投入 → 论文质量显著提升

---

## 七、一句话总结

> **冲击 A 的最优路径：Q0（代码根治，2小时）+ Q1-1（药效团，2小时）+ Q1-2（OpenMM quick，2小时）= 6小时 → 87/100。Q2 架构升级延后到计划开源时。**

---

*方案制定时间：2026-05-08*  
*基于：代码审查 + git 历史 + 测试分析 + 修复记录*
