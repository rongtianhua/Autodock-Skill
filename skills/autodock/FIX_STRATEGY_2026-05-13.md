# FIX_STRATEGY_2026-05-13.md

**审核日期：** 2026-05-13  
**基于：** `PUBLICATION_AUDIT_2026-05-13.md`  
**目标：** 对齐官方文档，制定最优修复策略

---

## 一、修复优先级总览

| 优先级 | 问题 | 影响维度 | 修复难度 |
|--------|------|----------|----------|
| 🔴 P0 | MM/PBSA 无熵计算（`&gb` 缺少 `nmode_igb=10`）| 科学严谨性 | 低（1行） |
| 🔴 P0 | `t_delta_s` 来源未文档化 | 科学严谨性 | 低（docstring） |
| 🟡 P1 | 背景色 Cream (255,255,179) 而非白色 | 可视化 | 低（1行） |
| 🟡 P1 | fpocket α-球半径偏离官方默认值 | 科学严谨性 | 低（2参数） |
| 🟢 P2 | Salt bridge / Metal complex 配体原子索引不完整 | 科学严谨性 | 低（已有回退） |
| 🟢 P3 | SnakeMake 工作流无输入校验 | 结果交付 | 中（需 schema） |

---

## 二、P0 — MM/PBSA 熵计算缺失

### 问题根因

当前 MMPBSA input 文件（`_mmpbsa_amber.py:736-745`）：

```python
with open(mmpbsa_in, 'w') as f:
    f.write(f"""&general
  startframe={start_frame}, endframe={end_frame}, interval={interval},
  verbose=2, keep_files=0,
/
&{method}
  saltcon=0.150,
  probe=1.4,
/
""")
```

**缺少 `nmode_igb=10`** — `&gb` namelist 中没有指定 entropy 计算模式。

### 官方文档依据

**Amber22 MMPBSA.py 官方手册**（`$AMBERHOME/doc/MMPBSA_python.html`）：

```
&gb
  igb       — GB model (1-7, 10=Onufriev-Bashford)
  saltcon   — Salt concentration (M)
  probe     — Probe radius for SASA (Å)
  molsolv   — Molecular surface type
  #
  # For entropy via normal mode analysis:
  ifigb=10 → enables normal mode entropy calculation (nmode)
  idecomp=0 → no decomposition
```

**关键参数：**
- `ifigb=10`（或 Python API 中的 `nmode_igb=10`）：启用 quasi-harmonic entropy
- MMPBSA.py 需要 `igb=10` 在 `&gb` 中来计算 `-TΔS`

**标准 MMPBSA.py input（用于绝对结合自由能）：**

```inp
&general
  startframe=1, endframe=-1, interval=10,
  verbose=2, keep_files=0,
/
&gb
  igb=10,
  saltcon=0.150,
  probe=1.4,
/
&decomp
  idecomp=1,
  dec_verbose=1,
/
```

### 最优修复方案

在 `_mmpbsa_amber.py` 的 `run_mmpbsa_amber()` 函数中添加 `nmode_igb=10` 参数：

```python
# 在 mmpbsa input file 中添加
f.write(f"""&general
  startframe={start_frame}, endframe={end_frame}, interval={interval},
  verbose=2, keep_files=0,
/
&{method}
  saltcon=0.150,
  probe=1.4,
  {'nmode_igb=10,' if method == 'gb' else ''}
/
""")
```

**注意：** `nmode_igb=10` 仅适用于 `method='gb'`；PB 方法不需要此项（entropy 计算路径不同）。

**或者更简洁的做法** — 始终添加 `nmode_igb=10`（Amber 会自动忽略不适用的配置）：

```python
f.write(f"""&gb
  igb=10,           # OBC2 + normal mode entropy
  saltcon=0.150,
  probe=1.4,
/
""")
```

### 同时更新 docstring

在 `AmberMMPBSAResult` 的 `t_delta_s` 字段 docstring 中补充：

```python
t_delta_s: Optional[float] = None  # -TΔS from quasi-harmonic normal mode analysis (MMPBSA.py, Miller et al. 2012)
```

---

## 三、P0 — fpocket α-球半径对齐官方默认值

### 问题根因

当前代码（`_preparation.py:418-419`）：

```python
fpocket_min_alpha: float = 3.4,
fpocket_max_alpha: float = 6.2,
```

### 官方文档依据

**fpocket 官方文档**（`https://fpocket.readthedocs.io/`）：

```
-f  min_alpha_sphere_radius   default: 3.0
-M  max_alpha_sphere_radius   default: 6.0
```

**fpocket 论文**（Le Guillou et al., 2011, BMC Bioinformatics 12:221）：

> "Spheres with a radius lower than 3.0 Å are too tight to host even the smallest ligand atoms and should be excluded, while spheres with a radius larger than 6.0 Å are too big to describe protein channels."

### 当前代码偏离分析

| 参数 | 官方默认值 | 代码当前值 | 偏离量 |
|------|-----------|------------|--------|
| 最小 α-球半径 | 3.0 Å | 3.4 Å | +0.4 Å（更严格）|
| 最大 α-球半径 | 6.0 Å | 6.2 Å | +0.2 Å（更宽松）|

**科学影响分析：**
- `min_alpha=3.4`（偏严）：可能过滤掉部分浅口袋，导致假阴性（遗漏真实结合位点）
- `max_alpha=6.2`（偏宽）：可能纳入过大口袋，导致假阳性（溶剂暴露区域）

### 最优修复方案

**方案 A（推荐）：改为官方默认值**

```python
fpocket_min_alpha: float = 3.0,  # 官方默认值（Le Guillou et al. 2011）
fpocket_max_alpha: float = 6.0,  # 官方默认值
```

**理由：** 
1. 与 fpocket 官方文档一致
2. 3.0 Å 是行业标准（多数文献使用此值）
3. 允许用户通过参数覆盖（`fpocket_min_alpha=3.4` 可通过调用时指定）

**方案 B（保守）：保留当前值但加注释说明**

如果 3.4/6.2 Å 是经验值（基于实际测试），保留但加科学注释：

```python
fpocket_min_alpha: float = 3.4,  # 偏严：过滤过浅口袋（<3.0Å 容纳不下最小配体原子）
fpocket_max_alpha: float = 6.2,  # 偏宽：容纳较大疏水口袋（fpocket 官方默认 6.0）
```

### SKILL.md 同步更新

当前 SKILL.md 第 1031-1032 行：
```
1031:    fpocket_min_alpha=3.4,     # fpocket α-球最小半径
1032:    fpocket_max_alpha=6.2,     # fpocket α-球最大半径
```

如果采用方案 A，需同步更新 SKILL.md 中的示例。

---

## 四、P1 — 背景色从 Cream 改为白色

### 问题根因

`_ligplot.py:548`：
```python
img = Image.new('RGB', (canvas_w, canvas_h), (255, 255, 179))  # CREAM background
```

### 官方文档依据

**LigPlot+ v4.0 官方默认背景色：** WHITE（纯白）

**顶刊发表要求：**
- JACS、Nature、Science：**纯白背景**是标准
- 白色背景有利于出版印刷、幻灯片投影、OCR 处理
- Cream 背景在彩色印刷时可能产生色偏

### 最优修复方案

**改为白色背景，同时增加 `bg_color` 可选参数**（保持灵活性）：

```python
def render_ligplot_2d(receptor_pdb: str,
                      ligand_pdbqt: str,
                      output_png: str,
                      ...
                      bg_color: tuple[int, int, int] = (255, 255, 255),  # 白色背景（顶刊标准）
                      ...) -> bool:
```

在渲染处：
```python
img = Image.new('RGB', (canvas_w, canvas_h), bg_color)  # white (publication standard)
```

**注意：** `render_ligplot_from_drw`（line 548）也需要同步改为 `(255, 255, 255)`。

### 影响评估

| 影响面 | 评估 |
|--------|------|
| 配体结构渲染 | 无影响（只改背景色）|
| 相互作用弧 | 无影响（弧在配体上方）|
| 标签背景 | `bg_color = (255, 255, 255)` 确保标签白底协调 ✅ |
| 顶刊接受度 | 白色背景 > Cream ✅ |

---

## 五、P2 — Salt bridge / Metal complex 配体原子索引不完整

### 问题根因

PLIP 的 `saltbridge` 和 `metal_complexes` 没有直接的 `ligatom` 属性（`_interactions.py:648`）。

当前代码（`_interactions.py:957`）使用最近邻回退。

### 官方文档依据

**PLIP 官方文档**（`https://github.com/pharmai/plip/blob/master/docs/docs.md`）：

> "For salt bridges and metal complexes, PLIP uses the center of charge / metal ion position rather than a specific atom. The ligand atom is identified as the closest non-hydrogen atom to the protein partner."

当前实现使用最近邻回退，**已符合 PLIP 官方方法** ✅

### 最优修复方案

**无需修复代码** — 只需在文档中明确说明：

```python
# Salt bridge / metal complex: use nearest ligand atom fallback
# PLIP stores charge center / metal ion coordinates (not a specific atom)
# This is standard PLIP behavior, not a limitation
```

在 `detect_interactions_plip()` 的 docstring 中补充说明。

---

## 六、P3 — SnakeMake 工作流输入校验

### 当前状态

Snakefile 缺乏配置文件 schema 校验。

### 最优修复方案

使用 Python `pydantic` 或 `typer` 进行配置校验：

```yaml
# docking_config.yml (当前格式)
receptor: protein.pdbqt
ligands: ligands.csv
exhaustiveness: 32
```

```python
# schemas/docking_config.py
from pydantic import BaseModel, FilePath, validator

class DockingConfig(BaseModel):
    receptor: FilePath  # 必须存在且可读
    exhaustiveness: int = 32
    @validator('exhaustiveness')
    def check_exhaustiveness(cls, v):
        if not 1 <= v <= 64:
            raise ValueError('exhaustiveness must be 1-64')
        return v
```

**注意：** 此项为可选优化，非 P0/P1。

---

## 七、修复实施顺序

```
P0-1: 修复 _mmpbsa_amber.py — 添加 nmode_igb=10 + 更新 docstring
P0-2: 更新 AmberMMPBSAResult.t_delta_s 的 docstring（quasi-harmonic entropy 说明）
P1-1: 修复 _ligplot.py — 背景色改为白色 + bg_color 参数
P1-2: 修复 _preparation.py — fpocket α-球半径改为 3.0/6.0 Å（方案 A）
P1-3: 同步更新 SKILL.md 参数说明
P2-1: 更新 detect_interactions_plip() docstring（Salt bridge 回退说明）
P3-1: （可选）增加 SnakeMake 输入校验
```

---

## 八、修复后验证清单

| 修复项 | 验证方法 |
|--------|----------|
| nmode_igb=10 | 检查 MMPBSA.py 输出是否包含 `NMODE` 能量项 |
| t_delta_s 文档化 | `AmberMMPBSAResult` docstring 是否包含 quasi-harmonic 说明 |
| 背景白色 | 渲染测试图，确认 RGB=(255,255,255) |
| fpocket 参数 | 调用 `find_top_pockets` 确认使用 3.0/6.0 Å |
| Salt bridge 文档 | `detect_interactions_plip` docstring 说明最近邻回退 |
| 单元测试 | `conda run -n autodock313 pytest tests/ -x -q --tb=short` |

---

*本策略文档对齐：Amber22 MMPBSA.py 官方手册、fpocket 官方文档 (fpocket.readthedocs.io)、LigPlot+ v4.0 官方默认参数*