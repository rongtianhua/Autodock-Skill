---
name: autodock-molecular-docking
description: |
  蛋白质与小分子药物的分子对接分析。
  AutoDock Vina 对接 + RDKit 相互作用检测 + PyMOL 可视化。
  支持 5 种 Publication-quality 渲染场景（complex / pocket / interaction / electrostatic / ligand_closeup）。
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

**Leipzig 标准虚线参数（应用在此函数中）：**

| 参数 | Leipzig 标准值 | 说明 |
|------|--------------|------|
| `dash_gap` | 0.4 | 虚线间隙 |
| `dash_radius` | 0.05 | 虚线圆柱半径 |
| `dash_length` | 0.3 | 每段虚线长度 |
| `dash_as_cylinders` | True | 圆柱形虚线（高质量）|
| `dash_width` | 2.5 | 虚线宽度 |

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

```python
from autodock import fetch_protein_pdb, fetch_protein_alphafold, fetch_protein

# RCSB 实验结构
fetch_protein_pdb("6LU7")

# AlphaFold AI 预测
fetch_protein_alphafold("Q9H825")

# 统一接口
fetch_protein(pdb_id="6LU7", source="pdb")
fetch_protein(uniprot_id="Q9H825", source="alphafold")
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
prepare_ligand("CCO", "ethanol.pdbqt")
```

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
)

best = energies[0][0]  # kcal/mol，越负越紧密
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

# 1. 获取结构
fetch_protein_alphafold("Q9H825")  # METTL8
mol = fetch_molecule_pubchem("Urolithin A")

# 2. 制备
prepare_receptor("./structures/AF-Q9H825.pdb", "./structures/METTL8.pdbqt")
prepare_ligand(mol['smiles'], "./structures/UrolithinA.pdbqt")

# 3. fpocket 自动找口袋
center, box = find_binding_site("./structures/AF-Q9H825.pdb")

# 4. 对接
dock_ligand("./structures/METTL8.pdbqt", "./structures/UrolithinA.pdbqt", center, box)

# 5. 检测相互作用
intx = detect_interactions(
    "./structures/METTL8.pdbqt",
    ligand_pdbqt="./docking_best.pdbqt",
    center=center,
)

# 6. 渲染（5 种场景）
render_scene("./structures/AF-Q9H825.pdb", "./results/complex.png",
             scene='complex', ligand_pdbqt="./docking_best.pdbqt")

render_scene("./structures/AF-Q9H825.pdb", "./results/pocket.png",
             scene='pocket', center=center, ligand_pdbqt="./docking_best.pdbqt")

render_scene("./structures/AF-Q9H825.pdb", "./results/interactions.png",
             scene='interaction', center=center, interactions=intx,
             ligand_pdbqt="./docking_best.pdbqt")
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
