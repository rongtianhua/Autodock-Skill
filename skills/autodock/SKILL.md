---
name: autodock-molecular-docking
description: |
  蛋白质与小分子药物的分子对接分析。
  AutoDock Vina 对接 + RDKit 相互作用检测 + PyMOL 可视化。
  支持 4 种 Publication-quality 渲染场景（complex / pocket / interaction / ligand_closeup）+ 综合四宫格拼接。
  基于 PyMOL 官方文档 / Leipzig 教程 / OPIG 最佳实践 / CB-Dock2 论文 调研优化（2026-04-25）。
tool_type: python
primary_tool: vina
---

## 环境

**必须激活 autodock313 环境：**

```bash
conda activate autodock313
```

路径：`/opt/homebrew/Caskroom/miniconda/base/envs/autodock313/`

包含：Python 3.13.13 / pymol-open-source 3.1.0 / RDKit 2026.03.1 / vina 1.2.5 / meeko 0.7.1 / fpocket 4.2.3

---

## 快速使用

```python
import sys
sys.path.insert(0, '~/.openclaw/workspace/skills/')
from autodock import (
    fetch_protein_pdb, fetch_molecule_pubchem,
    prepare_receptor, prepare_ligand,
    find_binding_site, dock_ligand,
    detect_interactions, render_scene,
    render_complex, render_pocket, render_interactions_pymol,
    composite_summary,
)

# 1. 获取结构
fetch_protein_pdb("6LU7")
mol = fetch_molecule_pubchem("nirmatrelvir")

# 2. 制备
prepare_receptor("protein.pdb", "protein.pdbqt")
prepare_ligand(mol['smiles'], "ligand.pdbqt")

# 3. 结合位点
center, box = find_binding_site("protein.pdb")

# 4. 对接
dock_ligand("protein.pdbqt", "ligand.pdbqt", center, box)

# 5. 检测相互作用
intx = detect_interactions("protein.pdb", ligand_pdbqt="docked.pdbqt", center=center)

# 6. 渲染（5 种场景可选）
render_scene("protein.pdb", "pocket.png",
             scene='pocket', center=center, interactions=intx,
             ligand_pdbqt="docked.pdbqt")

# 或直接用专用渲染器
render_interactions_pymol("protein.pdb", "docked.pdbqt", intx, center, "interactions.png")
```

---

## 渲染场景（5 种预设）

使用 `render_scene()` 或专用渲染器，选择适合你的工况：

| 场景 | 背景 | 蛋白 | 口袋 | 配体 | 相互作用 | 适用工况 |
|------|------|------|------|------|---------|---------|
| `complex` | 白 | cartoon（冷色）| — | gold sticks | — | 全景图 / TOC |
| `pocket` | 黑 | cartoon（半透明）| surface（bluewhite）| gold sticks + 球 | — | 口袋特写 |
| `interaction` | 黑 | cartoon（灰色）| lines（白色）| gold sticks | **H键/π-π/疏水虚线** | 相互作用分析 |
| `electrostatic` | 白 | cartoon | surface（APBS染色）| gold sticks | — | 静电势分析 |
| `ligand_closeup` | 黑 | 隐藏 | — | **球棍模型** | — | 配体结构说明 |

---

## render_scene — 通用场景渲染器

**（推荐使用，统一接口，自动应用研究级参数）**

```python
render_scene(
    pdb_path="protein.pdb",
    output_png="output.png",
    scene='pocket',           # 'complex' | 'pocket' | 'interaction' | 'electrostatic' | 'ligand_closeup'
    center=(x, y, z),        # 配体/对接盒子中心
    interactions=intx,        # detect_interactions() 返回的列表
    ligand_pdbqt="docked.pdbqt",  # 配体 PDBQT（可选，更精确）
    width=2400, height=1800, dpi=300,  # 出版质量
)
```

**场景覆盖场景：**

```python
# 全景图
render_scene(pdb_path, "complex.png", scene='complex',
             ligand_pdbqt="docked.pdbqt")

# 口袋特写（自动应用 surface transparency=0.25, ligand C=gold）
render_scene(pdb_path, "pocket.png", scene='pocket',
             center=center, ligand_pdbqt="docked.pdbqt")

# 相互作用图（自动应用 Leipzig dash 参数）
render_scene(pdb_path, "interactions.png", scene='interaction',
             center=center, interactions=intx, ligand_pdbqt="docked.pdbqt")
```

---

## render_complex — 复合体全景图

```python
render_complex(
    pdb_path="docked_complex.pdb",
    output_png="fig_complex.png",
    ligand_pdbqt="docked.pdbqt",   # 可选
    dpi=300, width=2400, height=1800,
)
```

**参数特点：**
- 背景：白
- 蛋白：rainbow cartoon
- 配体：gold sticks（C=gold，红/蓝/黄=N/O/S）
- 渲染：ray_trace_mode=0, ambient=0.5, antialias=4

---

## render_pocket — 口袋特写

```python
render_pocket(
    pdb_path="protein.pdb",
    output_png="fig_pocket.png",
    center=(x, y, z),
    ligand_pdbqt="docked.pdbqt",
    distance=5.0,     # 口袋半径（Å）
    show_labels=True,
    dpi=300,
)
```

**参数特点（CB-Dock2 风格）：**
- 背景：黑
- 蛋白 cartoon：transparency=0.15（半透明，透视口袋内部）
- 口袋表面：bluewhite，transparency=0.25
- 配体：C=gold, sticks + spheres
- 标签：白色，关键残基 CA 标注

---

## render_interactions_pymol — 相互作用标注图

**（推荐使用，已固化 Leipzig 标准 + 配体质心法，2026-04-25 实测验证）**

```python
render_interactions_pymol(
    receptor_pdb="protein.pdb",
    ligand_pdbqt="docked.pdbqt",
    interactions=intx,
    center=(x, y, z),
    output_png="fig_interactions.png",
    distance=5.0,
    dash_preset='fine',   # 'fine' (Leipzig) | 'standard' | 'bold'
    dpi=300,
)
```

**核心修复（2026-04-25）：PyMOL mode=0 虚线爆炸 → 配体质心法**

| 问题 | 原因 | 修复 |
|------|------|------|
| 疏水虚线数百条（应为 7 条）| PyMOL `mode=0` 对 `byres CA → ligand atoms` 产生 N×M 组合 | 改用配体质心 pseudoatom（`lig_cent`），每残基仅 1 条虚线 |
| cutoff=5.0 无法激活虚线 | PyMOL centroid 模式 cutoff 行为特殊，需 >9.5 Å | cutoff=10.0 |
| 残基标签重叠 | 动态标签自动排列差 | Hydrophobic 残基用橙色 sticks + CA 原子白标，H-bond/π-π 用 CA 标签 |

**Leipzig 标准虚线参数：**

| 参数 | Leipzig 标准值 | 说明 |
|------|--------------|------|
| `dash_gap` | 0.4 | 虚线间隙 |
| `dash_radius` | 0.05 | 虚线圆柱半径 |
| `dash_length` | 0.3（疏水 0.25）| 每段虚线长度 |
| `dash_as_cylinders` | True | 圆柱形虚线（高质量）|
| `dash_width` | 2.5 | 虚线宽度 |

**渲染内容（已固化）：**
- 背景：纯黑
- 蛋白：cartoon（灰色80，透明度 20%）
- 疏水残基：**橙色 sticks**（ALA85/TRP89/VAL203/GLY204/PHE231/VAL257/VAL279）
- 疏水虚线：**橙色，1条/残基， cutoff=10.0 Å**
- H-bond：青色虚线，cutoff=4.0 Å
- π-π：绿色虚线，cutoff=6.0 Å
- 残基标签：**白色字体（font_id=16, size=20）标注 CA 原子**
- 配体：gold sticks（C）+ red O
- 光照：ambient=0.5 / specular=0.6 / shininess=55（Leipzig）


**发表级四宫格标准布局（推荐）：**

| 面板 | 场景参数 | 内容 |
|------|---------|------|
| 左上 | `render_complex()` 或 `scene='full'` | 蛋白全长 cartoon + 配体 gold sticks + 结合位点黄色标记球 |
| 右上 | `render_pocket()` 或 `scene='pocket'` | 口袋蓝白渐变 surface |
| 左下 | `render_interactions_pymol()` | 橙色 sticks + 7条疏水虚线 + 残基白标 |
| 右下 | `scene='ligand_closeup'` | 配体 ball-and-stick 特写 |

**相互作用颜色：**
- H-bond → `cyan`（青色）
- π-π stacking → `green`（绿色）
- Hydrophobic → `orange`（橙色）

---

## detect_interactions — 相互作用检测

```python
from autodock import detect_interactions

intx = detect_interactions(
    receptor_pdb="protein.pdb",
    ligand_pdbqt="docked.pdbqt",   # 或 ligand_smiles="CCO"
    center=(x, y, z),
    distance=6.0,                  # 检测半径（Å）
    h_bond_max_angle=40.0,         # 供体-H-受体最大角度（度）
)

# intx[0] = {
#   'type': 'H-bond', 'color': 'cyan',
#   'resn': 'HIS', 'resi': 57, 'chain': 'A', 'atom': 'ND1',
#   'ligand_atom_idx': 3,
#   'distance': 2.9,
#   'description': 'H-bond: HIS57.A ND1 → N3'
# }
```

---

## 一、获取蛋白质结构

> ⚠️ **推荐：优先使用实验 PDB 结构，实验结构不可用时再 fallback 到 AlphaFold。**
> 
> 原因：PDB 晶体结构来自 X-ray/NMR/冷冻电镜，反映真实构象（含水分子、辅因子、变构位点），对接精度远高于 AI 预测。AlphaFold 可用于无实验结构时的快速预测，但结论需实验验证。

```python
from autodock import fetch_protein_pdb, fetch_protein_alphafold, fetch_protein

# ✅ 推荐：先尝试 RCSB 实验结构
fetch_protein_pdb("6LU7")

# Fallback：PDB 无结构时使用 AlphaFold
fetch_protein_alphafold("Q9H825")

# 自动 fallback 入口（推荐：优先 PDB → PDB-REDO → AlphaFold → SwissModel）
fetch_protein(uniprot_id="Q9H825")
```

### fetch_protein — 自动优先级链

```python
fetch_protein(pdb_id=None, uniprot_id=None, source='auto', output_dir='./structures')
```

**source='auto' 时（默认）：**
- `pdb_id` 给定 → 优先 RCSB PDB，失败则 PDB-REDO，再失败则用 `uniprot_id` fallback 到 AlphaFold
- 仅 `uniprot_id` → AlphaFold 优先，失败则 SwissModel

**显式指定 source：**
- `source='pdb'` — 只用 RCSB PDB
- `source='pdbredo'` — 只用 PDB-REDO
- `source='alphafold'` — 只用 AlphaFold
- `source='swissmodel'` — 只用 SwissModel

**若无 PDB ID，直接用：**
```python
fetch_protein_pdb("6LU7")           # 有 PDB ID，直接实验结构
fetch_protein_alphafold("Q9H825")  # 无 PDB ID，用 AlphaFold
```

---

## 二、获取小分子结构

```python
from autodock import fetch_molecule_pubchem

mol = fetch_molecule_pubchem("nirmatrelvir")
mol = fetch_molecule_pubchem("CC(=O)Oc1ccccc1C(=O)O", identifier_type='smiles')
print(mol['smiles'])
```

---

## 三、受体制备

```python
from autodock import prepare_receptor
prepare_receptor("protein.pdb", "protein.pdbqt")
```

---

## 四、配体制备

```python
from autodock import prepare_ligand

# 标准调用（seed=42 保证可重复的 3D 构象）
prepare_ligand("CCO", "ethanol.pdbqt", seed=42)

# 自定义随机种子（如需不同构象）
prepare_ligand("CCO", "ethanol.pdbqt", seed=123)
```

> **注意**：`seed` 参数控制 ETKDGv3 构象生成。固定种子确保每次运行产生相同的 3D 几何结构，便于结果复现。

---

## 五、结合位点定义

```python
from autodock import find_binding_site

# fpocket 自动预测（AlphaFold/Apo 蛋白首选）
center, box = find_binding_site("protein.pdb")

# 从共晶配体计算
center, box = find_binding_site("protein.pdb", ligand_pdb="co_ligand.pdb")
```

---

## 六、单配体对接

```python
from autodock import dock_ligand

energies, poses = dock_ligand(
    receptor_pdbqt="protein.pdbqt",
    ligand_pdbqt="ligand.pdbqt",
    center=(10.5, 20.3, 15.7),
    box_size=(20, 20, 20),
    exhaustiveness=8,
    receptor_pdb="protein.pdb",   # 可选：传入原始PDB以自动生成复合体PDB
)

best = energies[0][0]  # kcal/mol，越负越紧密

# 自动保存（无需手动）：
#   receptor_dir/docking_best.pdbqt   ← 对接配体 pose
#   receptor_dir/docked_complex.pdb   ← 蛋白+配体复合体（传入 receptor_pdb 时生成）
```

---

## 七、批量虚拟筛选

```python
from autodock import virtual_screen

ligands = {
    "compound_A": "CCO",
    "compound_B": "c1ccccc1",
    "compound_C": "CC(=O)Oc1ccccc1C(=O)O",
}

results_df = virtual_screen(
    receptor_pdbqt="protein.pdbqt",
    ligand_smiles_dict=ligands,
    center=(10.5, 20.3, 15.7),
    box_size=(20, 20, 20),
    output_dir="./docking_results",
)
```

---

## 八、综合输出（多面板）

```python
from autodock import composite_summary

composite_summary(
    panels=["fig_complex.png", "fig_pocket.png", "fig_interactions.png"],
    output_png="summary.png",
    ncols=3,
    panel_titles=["A. Protein-Ligand Complex", "B. Binding Pocket", "C. Interactions"],
    dpi=300,
    figure_title="Molecular Docking Results",
)
```

---

## 完整工作流示例（METTL8 + Urolithin A）

```python
import sys
sys.path.insert(0, '~/.openclaw/workspace/skills/')
from autodock import (
    fetch_protein_alphafold, fetch_molecule_pubchem,
    prepare_receptor, prepare_ligand,
    find_binding_site, dock_ligand,
    detect_interactions, render_scene,
    composite_summary,
)

# 1. 获取结构（自动优先级链：PDB → PDB-REDO → AlphaFold → SwissModel）
fetch_protein(uniprot_id="Q9H825")  # 自动选择最佳可用来源
mol = fetch_molecule_pubchem("Urolithin A")

# 2. 制备
prepare_receptor("./structures/METTL8.pdb", "./structures/METTL8.pdbqt")
prepare_ligand(mol['smiles'], "./structures/UrolithinA.pdbqt")

# 3. fpocket 自动找口袋
center, box = find_binding_site("./structures/METTL8.pdb")

# 4. 对接（传入 receptor_pdb=... 自动生成复合体PDB）
dock_ligand(
    receptor_pdbqt="./structures/METTL8.pdbqt",
    ligand_pdbqt="./structures/UrolithinA.pdbqt",
    center=center, box_size=box,
    exhaustiveness=32,
    receptor_pdb="./structures/AF-Q9H825.pdb",   # ← 传入PDB，自动生成复合体
)
# 自动生成：./structures/docking_best.pdbqt + ./structures/docked_complex.pdb

# 5. 检测相互作用（使用自动保存的 pose 文件）
intx = detect_interactions(
    receptor_pdb="./structures/AF-Q9H825.pdb",
    ligand_pdbqt="./structures/docking_best.pdbqt",
    center=center,
)

# 6. 渲染（5 种场景）
for scene in ['complex', 'pocket', 'interaction', 'electrostatic', 'ligand_closeup']:
    render_scene(
        "./structures/AF-Q9H825.pdb",
        f"./results/{scene}.png",
        scene=scene, center=center, interactions=intx,
        ligand_pdbqt="./structures/docking_best.pdbqt",
        width=2400, height=1800, dpi=300,
    )

# 7. 综合输出
composite_summary(
    panels=[
        "./results/complex.png",
        "./results/pocket.png",
        "./results/interaction.png",
    ],
    output_png="./results/summary.png",
    ncols=3,
    panel_titles=["A. Protein-Ligand Complex", "B. Binding Pocket", "C. Interactions"],
    figure_title="Molecular Docking: Urolithin A ↔ METTL8 (Q9H825)",
)
```

---

## 可视化参数来源说明（2026-04-25 调研）

| 来源 | 贡献 |
|------|------|
| PyMOL Official Docs (pymol.org/dokuwiki) | dash/surface/cartoon_* 全套参数 |
| Leipzig University PyMOL Tutorial | H-bond 虚线参数：dash_gap=0.4, dash_radius=0.05, dash_length=0.3 |
| OPIG "Making Pretty Pictures with PyMOL" | ambient=0.5, ray_trace_mode=1, surface_quality |
| CB-Dock2 paper (PMC9252749) | cavity 可视化流程，配体 gold + 口袋 bluewhite 配色 |
| APBS Electrostatics Plugin docs | 静电势表面染色：±5 kT/e，红蓝配色方案 |
| Wilson Lab PyMOL Cartoon Style | cartoon_ring_mode=3, cartoon_fancy_helices=1 |
