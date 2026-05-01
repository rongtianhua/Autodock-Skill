---
name: autodock-molecular-docking
description: |
  蛋白质与小分子药物的分子对接分析。
  AutoDock Vina 对接 + PLIP 相互作用检测 + RDKit cairo 2D 渲染 + PyMOL 3D 渲染。
  支持 2D/3D Publication-quality 可视化（300dpi PNG）。
  基于 PLIP 官方文档（2026-04）/ PyMOL 官方文档 / Leipzig 教程 / CB-Dock2 论文（2026-04-27 全面重构）。
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

## CLI 命令行入口

从 autodock skill 可直接通过命令行使用：

```bash
# 检查依赖
python -m autodock status

# 获取结构
python -m autodock fetch pdb 6LU7
python -m autodock fetch ligand aspirin

# 制备
python -m autodock prepare-receptor protein.pdb protein.pdbqt
python -m autodock prepare-ligand aspirin ligand.pdbqt

# 结合位点检测（fpocket + P2Rank）
python -m autodock find-site protein.pdb

# 对接
python -m autodock dock protein.pdbqt ligand.pdbqt \
    --center 10.5 20.3 -5.2 \
    --box-size 20 20 20 \
    --exhaustiveness 32 --n-poses 10

# 多构象对接（发表级标准，10 个构象分别对接取最优）
python -m autodock prepare-conformers 'CC(=O)OC1=CC=CC=C1C(=O)O' ./conformers/ --n 10
python -m autodock dock-multi-conformer protein.pdbqt conformers/ \
    --receptor-pdb protein.pdb --exhaustiveness 32

# 相互作用检测
python -m autodock detect-interactions protein.pdb ligand.pdbqt docked.pdbqt

# 渲染
python -m autodock render-2d protein.pdb ligand.pdbqt docked.pdbqt interaction.png
python -m autodock render-pymol protein.pdb ligand.pdbqt docked.pdbqt -o scene.png

# 虚拟筛选
python -m autodock virtual-screen protein.pdbqt library.csv results.csv \
    --center 10.5 20.3 -5.2 --box-size 20 20 20

# 验证（重对接）
python -m autodock validate protein.pdbqt crystal_ligand.pdbqt

# 全流程一键执行
python -m autodock run --receptor 6LU7 --ligand aspirin

# 静默/调试模式
python -m autodock -q status          # 只显示警告和错误
python -m autodock -v dock ...        # 详细调试信息
```

**使用说明：**
- 所有 `python -m autodock` 命令需在 `autodock313` 环境下运行
- `-q` 静默模式适合脚本批量运行
- `-v` 详细模式适合调试对接参数

---

## Python API 快速使用

```python
import sys
sys.path.insert(0, '~/.openclaw/workspace/skills/')
from autodock import (
    fetch_protein_pdb, fetch_molecule_pubchem,
    prepare_receptor, prepare_ligand,
    find_binding_site, dock_ligand,
    detect_interactions, detect_interactions_plip,
    render_scene, render_complex, render_pocket,
    render_interactions_pymol, render_interactions_2d,
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

# ── 多构象配体（发表级对接标准）
# 标准单构象对接：生成 1 个随机构象，Vina 只在这个构象基础上采样
# 多构象对接：生成 N 个独立构象，分别对接，合并结果 → 全局最优
conformers = prepare_ligand_conformers(
    mol['smiles'], "./conformers/", n_conformers=10)
# conformers = ['./conformers/conformer_0.pdbqt', ..., './conformers/conformer_9.pdbqt']

result = dock_ligand_multi_conformer(
    receptor_pdbqt, conformers,
    receptor_pdb=receptor_pdb,
    exhaustiveness=32, n_poses=10,
)
print(f"Best energy: {result['best_energy']:.2f} kcal/mol")

# ── 结构缓存（自动管理，不需手动清理）
# 首次下载后自动缓存到 ~/.openclaw/structures_cache/
# 再次使用同名结构时直接从缓存返回，无网络开销
from autodock import clear_cache, get_cache_info

info = get_cache_info()          # 查看缓存占用
print(f"Cached: {info['n_files']} files, {info['size_mb']:.1f} MB")

cleared = clear_cache(confirm=True)  # 交互式清除（需确认）
cleared = clear_cache(confirm=False) # 静默清除（自动化脚本用）
print(f"Freed: {cleared['size_mb']:.1f} MB")
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

## detect_interactions_plip — PLIP 2D 相互作用检测（推荐）

**（2026-04-27 全面修复，已解决 PLIP 3.0 / PDBQT 解析 / RDKit 3D 坐标全链路问题）**

**（2026-04-30 修复 substrate 竞争 bug：receptor_pdb 必须传 crystal PDB，含 GLY/TYR HETATM 的 PDB 会自动处理）**

```python
from autodock import detect_interactions_plip, render_interactions_2d

# Step 1: PLIP 相互作用分析
# receptor_pdb 必须是 crystal PDB（含 REMARK 800 活性位点标记）。
# 若 crystal 含共结晶配体（HETATM 如 GLY/TYR 二肽），函数内部自动将其
# 转换为 ATOM 记录（PLIP 视为蛋白残基而非配体），避免站点选择竞争。
intx, xml_report = detect_interactions_plip(
    receptor_pdb="6LU7.pdb",
    ligand_pdbqt="nirmatrelvir_docked.pdbqt",
)
```
# intx[0] = {
#   'type': 'H-bond', 'color': 'cyan',
#   'resn': 'PHE', 'resi': 140, 'chain': 'A', 'atom': 'N',
#   'ligand_atom_idx': 1,        # ← RDKit 原子索引（用于 2D 高亮）
#   'distance': 2.55,
#   'description': 'H-bond: PHE140 -> UNL1 (2.55 A, ang-161)'
# }

# Step 2: RDKit cairo 渲染 2D 相互作用图（300dpi 发表质量）
render_interactions_2d(
    receptor_pdb="6LU7.pdb",
    ligand_pdbqt="nirmatrelvir_docked.pdbqt",
    interactions=intx,
    output_png="interactions_2d.png",
    width=900, height=700, dpi=300,
)
```

**支持 9 种相互作用类型（均已完整实现 2D 渲染）：**

| 类型 | 颜色 | 说明 | 2D 高亮 | 状态 |
|------|------|------|:------:|------|
| H-bond (配体供体) | 🔵 青色 | 氢键，配体提供 H | ✅ | ✅ 完整 |
| H-bond (蛋白供体) | 🔵 青色 | 氢键，蛋白提供 H | ✅ | ✅ 完整 |
| π-π stacking | 🟢 绿色 | 芳环堆积 | ✅ | ✅ 完整 |
| π-cation (芳环) | 🟣 紫色 | π-阳离子（芳环-正电）| ✅ | ✅ 完整 |
| π-cation (脂肪) | 🟣 紫色 | π-阳离子（脂肪-正电）| ✅ | ✅ 完整 |
| Hydrophobic | 🟠 橙色 | 疏水接触 | ✅ | ✅ 完整 |
| Salt bridge | 🔴 红色 | 盐桥（双线渲染，坐标来源为带电中心）| ✅ | ✅ 完整 |
| Halogen bond | 🟡 黄色 | 卤键 | ✅ | ✅ 完整 |
| Water bridge | 🔷 蓝色 | 水桥（配体原子 item.d，双线渲染）| ✅ | ✅ 完整 |
| Metal complex | ⚪ 灰色 | 金属络合（双线渲染，坐标来源为金属离子）| ✅ | ✅ 完整 |

**说明：**
- 所有 9 种相互作用均已实现 2D dummy atom + 分子线/双线/虚线/箭头渲染
- Salt bridge / Water bridge / Metal complex 使用双线样式（`double`）
- Salt bridge 的坐标来源为带电中心（charge center）而非单个原子，可能存在亚原子级偏移
- PLIP 原生报告（XML）始终包含完整的文字描述，不受 2D 坐标精度影响
- PLIP 定义共 11 种类型（另含 waters/water_bridge 个体计数），本技能覆盖上述 9 种核心相互作用类型

**2D 渲染技术细节（供调试参考）：**
- ✅ 完整：PLIP 提供完整 pybel Atom 坐标 → RDKit dummy atom → Cairo 渲染
- ⚠️ 坐标偏移：Salt bridge / Metal complex 使用 charge center / metal ion 坐标，dummy atom 位置为带电中心而非特定原子，可能存在亚原子偏移（<1 Å），但不影响相互作用双线渲染

---

## render_interactions_2d — RDKit cairo 2D 渲染（PNG + PDF 矢量）

**技术路线：PLIP 检测 + RDKit dummy atom + ZERO bond + Cairo 渲染 + cairosvg PDF 导出**

```python
render_interactions_2d(
    receptor_pdb="protein.pdb",
    ligand_pdbqt="docked.pdbqt",
    interactions=intx,
    output_png="interactions_2d.png",   # PNG 300dpi（点阵）
    output_pdf="interactions_2d.pdf",   # PDF 矢量（发表级）
    width=1000,    # 像素宽度
    height=800,    # 像素高度
    dpi=300,       # PNG DPI（发表标准 300）
)
```

**特点：**
- PNG：300dpi 点阵，含完整图例（Interactions）+ 残基标注（PHE140.A 等）
- PDF：矢量格式，分子线条+文字均为矢量，Helvetica 渲染正常
- 输出 PNG + PDF 可同时生成，也可只选其一（`output_pdf=None` 则只输出 PNG）
- 支持 dummy atom circle highlight（RDKit circleAtoms）+ 虚线/双线/箭头后处理

**PNG 和 PDF 的区别：**

| 属性 | PNG | PDF |
|------|-----|-----|
| 格式 | 点阵 300dpi | 矢量 |
| 图例 | ✅ PIL overlay | ✅ SVG text 注入 |
| 残基标签 | ✅ PIL overlay | ✅ SVG text 注入 |
| 分子结构 | RDKit Cairo | RDKit SVG → cairosvg |
| 文件大小 | ~50KB | ~16KB |
| 适用场景 | 幻灯片/Word | 发表论文（矢量） |

**配合 PyMOL 3D 图使用（推荐发表布局）：**

| 面板 | 工具 | 内容 |
|------|------|------|
| 左图 | `render_interactions_pymol()` | 3D 口袋 + 虚线标注 |
| 右图 | `render_interactions_2d()` | 2D 分子骨架 + 原子高亮 |

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

# 方式 1：仅返回内存结果（poses 不持久化）
energies, poses = dock_ligand(
    receptor_pdbqt="protein.pdbqt",
    ligand_pdbqt="ligand.pdbqt",
    center=(10.5, 20.3, 15.7),
    box_size=(20, 20, 20),
    exhaustiveness=8,
)
best = energies[0][0]  # kcal/mol，越负越紧密

# 方式 2：持久化 Pose 文件到指定目录（推荐，用于下游分析）
energies, poses, meta = dock_ligand(
    receptor_pdbqt="protein.pdbqt",
    ligand_pdbqt="ligand.pdbqt",
    center=(10.5, 20.3, 15.7),
    box_size=(20, 20, 20),
    exhaustiveness=32,
    receptor_pdb="protein.pdb",   # 用于 include_interactions / include_clash
    include_interactions=True,      # 同时检测相互作用
    output_dir="./structures",     # ← 关键：保存 pose 文件到 ./structures/
)
# 输出文件：
#   ./structures/docking_best.pdbqt     ← 最佳 pose（Vina rank #1）
#   ./structures/docking_all_poses.pdbqt ← 所有 n_poses
#   meta['interactions']               ← 相互作用列表（include_interactions=True）
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

# 3. fpocket + P2Rank 自动找口袋（优先用 find_top_pockets）
pockets = find_top_pockets("./structures/METTL8.pdb", ligand_pdb=None, padding=5.0, max_pockets=3, use_p2rank=True)
# pockets 是按 P2Rank 概率排序的列表，取概率最高的口袋
pocket = pockets[0]  # {center, box_size, p2rank_prob, druggability}
center = pocket['center']
box_size = pocket['box_size']

# 4. 对接（output_dir 持久化 Pose 文件）
# 重要：能量最低的 pose 不一定是质量最佳的（需参考 clash score）
# 建议 n_poses≥10，然后按 "energy < -8 + clash < 1.2" 筛选最优 pose
energies, poses, meta = dock_ligand(
    receptor_pdbqt="./structures/METTL8.pdbqt",
    ligand_pdbqt="./structures/UrolithinA.pdbqt",
    center=center, box_size=box_size,
    exhaustiveness=32,
    n_poses=10,  # 建议取多个 pose 再筛选
    receptor_pdb="./structures/AF-Q9H825.pdb",   # 用于相互作用检测
    include_interactions=True,                      # 同时检测相互作用
    output_dir="./structures",                     # ← 保存 pose 文件
)
# 生成文件：
#   ./structures/docking_best.pdbqt     ← 最佳 pose（Vina rank #1）
#   ./structures/docking_all_poses.pdbqt ← 全部 10 个 poses
#   meta['interactions']                 ← 相互作用列表

# 5. 检测相互作用（使用持久化的 pose 文件）
#    若未使用 include_interactions，可手动调用：
intx = meta.get('interactions')  # 已包含在 meta 中
# 或者手动调用：
# intx = detect_interactions(
#     receptor_pdb="./structures/AF-Q9H825.pdb",
#     ligand_pdbqt="./structures/docking_best.pdbqt",
#     center=center,
# )


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
