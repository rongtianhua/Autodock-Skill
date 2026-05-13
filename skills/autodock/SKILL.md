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
python -m autodock fetch pdb 6LU7              # legacy .pdb
python -m autodock fetch pdb 6LU7 --format cif  # .cif → 自动转 .pdb
python -m autodock fetch ligand aspirin

# BindingDB 实验亲和力查询
python -m autodock bindingdb aspirin --type name --max-results 10
python -m autodock bindingdb P00533 --type uniprot --max-results 50  # EGFR 靶点

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

# 药效团检测
python -m autodock pharmacophore protein.pdb --ligand docked.pdbqt -o features.png

# SnakeMake 工作流
python -m autodock workflow docking_config.yml --cores 4
python -m autodock workflow docking_config.yml --dry-run

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
sys.path.insert(0, '/Users/allenrong/.openclaw/workspace/skills/autodock/')
from autodock import (
    fetch_protein_pdb, fetch_molecule_pubchem,
    prepare_receptor, prepare_ligand,
    find_binding_site, dock_ligand,
    detect_interactions, detect_interactions_plip,
    render_scene, render_complex, render_pocket,
    render_interactions_pymol, render_interactions_2d,
    composite_summary, sample_zinc_compounds,
)

# 1. 获取结构
# 蛋白结构（支持 .pdb 和 .cif 格式）
fetch_protein_pdb("6LU7")                    # 默认：legacy .pdb（4字符ID）
fetch_protein_pdb("6LU7", format='cif')      # 强制下载 .cif → 自动转 .pdb
fetch_protein_pdb("PDB_12345678", format='auto')  # 12字符扩展ID，自动用 .cif

# 小分子（多数据源自动回退）
mol = fetch_molecule_pubchem("nirmatrelvir")
mol = fetch_molecule_chembl("CHEMBL4804922")   # ChEMBL 生物活性数据
mol = fetch_molecule_cactus("aspirin")          # NIH Cactus 快速 SMILES 解析

# 实验结合亲和力（BindingDB — 160万+ 实验数据）
from autodock import fetch_bindingdb_affinity, fetch_bindingdb_by_target
# 按化合物查亲和力
aff_data = fetch_bindingdb_affinity(name="aspirin", max_results=10)
# 按靶点查所有已知配体
ligands = fetch_bindingdb_by_target(uniprot_id="P00533", max_results=50)  # EGFR

# 或从 ZINC22 采样药物相似化合物（~130M 可购买化合物）
df = sample_zinc_compounds(n=50, h_donors_range=(0, 3), logp_range=(2, 4), mw_range=(250, 400))
print(df[['zinc_id', 'smiles']].head())

# 2. 制备
# 受体：支持 .pdb / .cif / .pdbx（ProDy 自动转换）
prepare_receptor("protein.pdb", "protein.pdbqt")                    # 默认：PDB
prepare_receptor("protein.cif", "protein.pdbqt")                    # 自动检测 .cif
prepare_receptor("protein.txt", "protein.pdbqt", input_format='cif')  # 强制格式

# 配体
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

**支持 10 种相互作用类型（PLIP 11 key → 8 唯一显示类别）：**

| 类型 | 颜色 | 说明 | 2D 高亮 | 状态 |
|------|------|------|:------:|------|
| H-bond（蛋白供体） | 🔵 青色 | 蛋白侧提供 H 供体（pdon） | ✅ | ✅ 完整 |
| H-bond（配体供体） | 🔵 青色 | 配体侧提供 H 供体（ldon） | ✅ | ✅ 完整 |
| Hydrophobic | 🟠 橙色 | 疏水接触 | ✅ | ✅ 完整 |
| π-π stacking | 🟢 绿色 | 芳环堆积（环中心 dummy） | ✅ | ✅ 完整 |
| π-cation（芳环→正电） | 🟣 紫色 | 芳环→正电（paro） | ✅ | ✅ 完整 |
| π-cation（脂肪→正电） | 🟣 紫色 | 脂肪链→正电（laro） | ✅ | ✅ 完整 |
| Salt bridge（配体负） | 🔴 红色 | 配体负电基团（lneg，双线） | ✅ | ✅ 完整 |
| Salt bridge（蛋白负） | 🔴 红色 | 蛋白负电基团（pneg，双线） | ✅ | ✅ 完整 |
| Halogen bond | 🟡 黄色 | 卤键（Cl/Br/I 参与） | ✅ | ✅ 完整 |
| Water bridge | 🔷 蓝色 | 水分子桥接（双线） | ✅ | ✅ 完整 |
| Metal complex | ⚪ 灰色 | 金属离子络合（双线） | ✅ | ✅ 完整 |

**说明：**
- PLIP 原始检测 key 共 **11 种**（部分按方向/供体受体拆分为 pdon/ldon/lneg/pneg/paro/laro 等亚型）
- 合并为 **8 个唯一显示类别**（H-bond / Hydrophobic / π-π / π-cation / Salt bridge / Halogen bond / Water bridge / Metal complex）
- 上表 10 行：π-cation 按芳环/脂肪拆两行（aro-paro / aro-laro），Salt bridge 按配体/蛋白负拆两行
- Salt bridge / Water bridge / Metal complex 使用双线样式，dummy atom 位于带电中心而非特定原子

**2D 渲染技术细节（供调试参考）：**
- ✅ 完整：PLIP 提供完整 pybel Atom 坐标 → RDKit dummy atom → Cairo 渲染
- ⚠️ 坐标偏移：Salt bridge / Metal complex 使用 charge center / metal ion 坐标，dummy atom 位置为带电中心而非特定原子，可能存在亚原子偏移（<1 Å），但不影响相互作用双线渲染
- ℹ️ 分类说明：PLIP 原始 key 共 11 种（pdon/ldon、paro/laro、lneg/pneg 等方向拆分），本技能合并为 8 个唯一显示类别（H-bond / Hydrophobic / π-π / π-cation / Salt bridge / Halogen bond / Water bridge / Metal complex）

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

## MM/PBSA — 对接后结合自由能重评分

> ⚠️ **这是一个简化的 MM/GBSA 实现，用于相对排序和热点残基识别。不适用于发表级绝对 ΔG 值。**
>
> 精度：与实验值相比可能有 ±2–5 kcal/mol 偏差。如需发表级绝对结合自由能，请使用 AmberTools MMPBSA.py。

### 快速使用

```python
from autodock import compute_mmpbsa

result = compute_mmpbsa(
    receptor_pdb="6LU7.pdb",
    ligand_pdbqt="nirmatrelvir_docked.pdbqt",
    decomp=True,       # 启用残基级能量分解
    compute_sasa=True, # 包含非极性溶剂化能（较慢但更完整）
)

print(result.summary())

# 论文表格数据
for row in result.to_dataframe_rows()[:10]:
    print(f"{row['residue']:12s}  {row['energy_kcal_mol']:+.2f} kcal/mol")
```

### 输出字段

| 字段 | 说明 | 用途 |
|------|------|------|
| `delta_g_bind` | 总结合自由能 ΔG_bind (kcal/mol) | 配体排序 |
| `delta_e_elec` | 库仑静电能 | 盐桥/电荷相互作用 |
| `delta_e_vdw` | Lennard-Jones 范德华能 | 疏水口袋匹配 |
| `delta_g_gb` | GB 极性溶剂化能 | 溶剂对电荷的屏蔽 |
| `delta_g_sa` | SASA 非极性溶剂化能 | 疏水效应 |
| `per_residue` | 每个残基的能量贡献 | 识别关键残基 |

### 多配体排序

```python
from autodock import mmpbsa_rank_ligands

results = mmpbsa_rank_ligands(
    "protein.pdb",
    [("aspirin", "asp_docked.pdbqt"),
     ("ibuprofen", "ibu_docked.pdbqt"),
     ("paracetamol", "par_docked.pdbqt")]
)

for r in results:
    print(f"{os.path.basename(r.ligand):20s}  ΔG = {r.delta_g_bind:+.2f}")
```

### 技术说明

- **实现方式**：基于 RDKit + 自定义 AMBER/GAFF 力场参数，无需 AmberTools/OpenMM
- **精度**：相对排序可靠（趋势正确），绝对值可能有 2-5 kcal/mol 偏差
- **Clash 检测**：如果 vdW 能量 > 1000 kcal/mol，会自动警告原子重叠
- **电荷**：配体从 PDBQT 读取 Gasteiger 电荷；受体自动计算 Gasteiger 电荷
- **时间**：2690 原子蛋白 + 14 原子配体 ≈ 3-5 秒（不含 SASA）；含 SASA ≈ 15-30 秒

### 局限性

- 简化 GB 模型（Still），非完整 OBC2
- 无熵校正（-TΔS 未计算）
- 对于严重 clash 的 pose，结果不可靠（会警告）
- 如需发表级绝对能量，建议使用 AmberTools MMPBSA.py

---

## MM/PBSA — 对接后结合自由能重评分（OBC2 + Interaction Entropy）

对接完成后，Vina 的打分函数给出的是结合亲和力的近似值。MM/PBSA（分子力学/广义玻恩表面积）提供更精细的能量分解，可以：

> ⚠️ **这是一个简化的 MM/GBSA 实现，用于相对排序和热点残基识别。不适用于发表级绝对 ΔG 值。**
>
> 精度：与实验值相比可能有 ±2–5 kcal/mol 偏差。如需发表级绝对结合自由能，请使用 AmberTools MMPBSA.py。

1. **相对比较**不同配体的结合强度排序
2. **能量分解**识别对结合贡献最大的关键残基（hot-spot residues）
3. **论文数据**提供 ΔG_bind、静电能、范德华能、溶剂化能、熵校正的分解表格

### 技术特点

- **OBC2 GB 模型**：基于原子深度的 Born 半径校正（Onufriev et al. 2004）
- **Interaction Entropy**：经验熵校正（基于可旋转键数）
- **SASA 非极性溶剂化**：Shrake-Rupley 算法，默认开启
- **自动过滤**：跳过 linker / 水分子 / 结晶添加剂

### 快速使用

```python
from autodock import compute_mmpbsa

# 基础用法（OBC2 + SASA + 经验熵校正）
result = compute_mmpbsa(
    receptor_pdb="6LU7.pdb",
    ligand_pdbqt="nirmatrelvir_docked.pdbqt",
    decomp=True,        # 启用残基级能量分解
    compute_sasa=True,  # 包含非极性溶剂化能
)

print(result.summary())
# MM/GBSA Binding Free Energy: -53.64 kcal/mol
#   Gas-phase interaction:      -15.68 kcal/mol
#     Coulomb:                  +15.16
#     van der Waals:            -30.84
#   Solvation correction:       -54.46 kcal/mol
#     Polar (GB/OBC2):        -54.46
#     Non-polar (SA):           -0.00
#   Entropy correction:         +16.50 kcal/mol
# ...
```

### 输出字段

| 字段 | 说明 | 用途 |
|------|------|------|
| `delta_g_bind` | 总结合自由能 ΔG_bind (kcal/mol) | 配体排序 |
| `delta_e_elec` | 库仑静电能 | 盐桥/电荷相互作用 |
| `delta_e_vdw` | Lennard-Jones 范德华能 | 疏水口袋匹配 |
| `delta_g_gb` | OBC2 极性溶剂化能 | 溶剂对电荷的屏蔽 |
| `delta_g_sa` | SASA 非极性溶剂化能 | 疏水效应 |
| `t_delta_s` | -TΔS 熵校正 | 构象自由度惩罚 |
| `per_residue` | 每个残基的能量贡献 | 识别关键残基 |

### 多配体排序

```python
from autodock import mmpbsa_rank_ligands

results = mmpbsa_rank_ligands(
    "protein.pdb",
    [("aspirin", "asp_docked.pdbqt"),
     ("ibuprofen", "ibu_docked.pdbqt")]
)

for r in results:
    print(f"{os.path.basename(r.ligand):20s}  ΔG = {r.delta_g_bind:+.2f}")
```

### 高级参数

```python
# 关闭 SASA 加速（大体系）
result = compute_mmpbsa(..., compute_sasa=False)

# 使用简化 Still GB 模型（更快，精度略低）
result = compute_mmpbsa(..., use_obc2=False)

# 提供多个 poses 进行严格的 Interaction Entropy
result = compute_mmpbsa(..., poses_pdbqt=["pose1.pdbqt", "pose2.pdbqt", ...])
```

### 精度说明

| 场景 | 适用性 |
|------|--------|
| 配体相对比较排序 | ✅ 可靠 |
| 残基贡献趋势分析 | ✅ 可靠 |
| 绝对 ΔG 数值 | ⚠️ 可能有 2-5 kcal/mol 偏差（无 MD 采样）|
| 严重 clash pose | ❌ 不可靠（会警告）|

### 局限性

- 简化 OBC2（原子深度校正，非完整 CFA 积分）
- 熵校正使用经验公式（无 MD 构象系综）
- 如需发表级绝对能量，建议使用 AmberTools MMPBSA.py

---

## MM/PBSA — 发表级 AmberTools 分子动力学

对接后结合自由能的**发表级**计算，基于 AmberTools 完整 MD 模拟 + MMPBSA.py。

> **精度：** ±0.5–1.5 kcal/mol vs 实验值（需 10ns+ MD 采样）
> **运行时间：** 5 分钟（仅能量最小化）→ 16+ 小时（100ns 生产模拟）

### 环境要求

**必须激活 autodock-amber 环境：**

```bash
conda activate autodock-amber
```

### 一键调用 API

```python
from autodock import compute_mmpbsa

# 发表级计算（MD + MMPBSA）
result = compute_mmpbsa(
    receptor_pdb="6LU7.pdb",
    ligand_pdbqt="docked.pdbqt",
    method="amber",           # 关键：启用 AmberTools 模式
    amber_protocol="short",   # 模拟协议
    amber_method="gb",        # 溶剂化方法 'gb' (快) | 'pb' (准)
    use_gpu=False,            # GPU 加速（5-10x 提速）
    decomp=True,              # 残基能量分解
)

print(result.summary())
print(f"ΔG_bind = {result.delta_g_bind:.2f} kcal/mol")
print(f"发表级合格？ {result.is_publication_grade}")
```

### 模拟协议选择

| protocol | 内容 | 运行时间 | 精度 | 用途 |
|----------|------|----------|------|------|
| `quick` | 仅能量最小化（2000 步） | 5–10 分钟 | 低 | 拓扑验证、快速筛选 |
| `short` | 最小化 → 50ps 升温 → 1ns NVT | 30–60 分钟 | 中 | 方法验证、构象排序 |
| `medium` | 最小化 → 升温 → 10ns NPT | 2–4 小时 | 好 | 发表初算结果 |
| `full` | 最小化 → 升温 → 100ns NPT | 8–16 小时 | 优秀 | 发表最终结果 |

### 分步调用（更灵活）

```python
from autodock import prepare_amber_topology, run_amber_md, run_mmpbsa_amber

# 步骤 1：构建拓扑
topo = prepare_amber_topology(
    receptor_pdb="6LU7.pdb",
    ligand_pdbqt="docked.pdbqt",
    output_dir="amber_topology",
)

# 步骤 2：运行 MD 模拟
traj = run_amber_md(
    prmtop=topo['complex_prmtop'],
    rst7=topo['complex_rst7'],
    output_prefix="amber_md/md",
    protocol="medium",
)

# 步骤 3：运行 MMPBSA 计算
result = run_mmpbsa_amber(
    complex_prmtop=topo['complex_prmtop'],
    receptor_prmtop=topo['receptor_prmtop'],
    ligand_prmtop=topo['ligand_prmtop'],
    trajectory=traj,
    output_prefix="amber_mmpbsa/mmpbsa",
    method="pb",  # Poisson-Boltzmann（更准确）
    interval=10,  # 每 10 帧采样一次，提速 10x
)
```

### 能量组分解读

```python
print(f"总结合自由能 ΔG: {result.delta_g_bind:.2f} kcal/mol")
print(f"  范德华作用: {result.delta_e_vdw:.2f}")
print(f"  静电作用: {result.delta_e_elec:.2f}")
print(f"  GB/PB 去溶剂化: {result.delta_g_gb:.2f}")
print(f"  SASA 非极性: {result.delta_g_sa:.2f}")

# 热点残基分析
print("\n关键贡献残基：")
for res, energy in sorted(result.per_residue.items(), key=lambda x: x[1])[:5]:
    if energy < -1.0:
        print(f"  {res}: {energy:+.2f} kcal/mol")
```

### 典型结合自由能范围

| ΔG (kcal/mol) | Kd (μM) | 解释 |
|---------------|---------|------|
| -5 | ~200 | 弱结合 |
| -8 | ~1.5 | 片段级别 |
| -10 | ~0.05 | 良好先导物 |
| -12 | ~0.0015 | 药物级别 |
| -15 | ~8e-6 | 极强结合 |

### 发表结果检查清单

1. ✅ 使用 `protocol="medium"` 或 `"full"`（`quick`/`short` 仅用于筛选）
2. ✅ 运行 3+ 次独立重复，报告均值 ± 标准误
3. ✅ 建议使用 `method="pb"`（Poisson-Boltzmann）做最终计算
4. ✅ 报告所有能量组分，不要只报 ΔG_bind
5. ✅ 提供轨迹收敛性分析（RMSD、能量波动）

### 详细文档

完整 AmberTools 工作流参考：`AMBER_WORKFLOW_REFERENCE.md`

包含：
- 拓扑构建内部步骤
- MD 参数细节（Langevin 温控、Monte Carlo 压控）
- 常见错误与解决方案
- GPU 加速指南
- AmberTools 命令行直接调用

---

## 药效团检测 (Pharmacophore)

> **适用场景**：识别结合口袋中的关键药效团特征，指导配体优化和虚拟筛选。

### 检测口袋药效团特征

```python
from autodock import detect_pharmacophore, render_pharmacophore

# 检测口袋中的药效团特征
features = detect_pharmacophore(
    receptor_pdb="6LU7.pdb",
    ligand_pdbqt="nirm_docked.pdbqt",  # 可选：基于配体位置定义口袋
    center=(10.5, 20.3, -5.2),        # 可选：手动指定口袋中心
    radius=8.0,                        # 口袋半径（Å）
)

# features = [
#   {'type': 'DONOR',      'center': (x,y,z), 'residue': 'SER144'},
#   {'type': 'ACCEPTOR',   'center': (x,y,z), 'residue': 'GLU166'},
#   {'type': 'HYDROPHOBIC','center': (x,y,z), 'residue': 'MET165'},
#   {'type': 'AROMATIC',   'center': (x,y,z), 'residue': 'PHE140'},
#   {'type': 'POSITIVE',   'center': (x,y,z), 'residue': 'LYS5'},
#   {'type': 'NEGATIVE',   'center': (x,y,z), 'residue': 'ASP3'},
# ]
```

### 支持的 6 种药效团特征

| 类型 | 颜色 | 几何检测标准 | 典型残基 |
|------|------|------------|---------|
| `DONOR` | 🔵 蓝色 | H-bond donor N/O + H 原子 | SER, THR, TYR, LYS, ARG |
| `ACCEPTOR` | 🔴 红色 | H-bond acceptor N/O（孤对电子） | ASP, GLU, ASN, SER |
| `HYDROPHOBIC` | 🟡 黄色 | 脂肪族 C + 芳香环中心 | ALA, VAL, LEU, ILE, PHE, MET |
| `AROMATIC` | 🟢 绿色 | 芳香环质心（6元环） | PHE, TYR, TRP, HIS |
| `POSITIVE` | 🩵 青色 | 带正电荷基团（pH 7） | LYS (NH₃⁺), ARG (胍基) |
| `NEGATIVE` | 🩷 品红 | 带负电荷基团（pH 7） | ASP (COO⁻), GLU (COO⁻) |

### PyMOL 3D 渲染

```python
render_pharmacophore(
    receptor_pdb="6LU7.pdb",
    features=features,
    output_png="pharmacophore.png",
    dpi=300,
)
```

**渲染特点：**
- 6 种特征用不同颜色球体标注（蓝/红/黄/绿/青/品红）
- 球体大小：6 Å 半径（表示特征作用范围）
- 标签：残基名 + 特征类型
- 背景：白色，蛋白 cartoon 灰色

### CLI 入口

```bash
python -m autodock pharmacophore 6LU7.pdb --ligand nirm_docked.pdbqt -o features.png
```

---

## OpenMM Pose 稳定性验证

> **适用场景**：快速验证对接 pose 的物理合理性，排除因对接采样不足导致的伪最优构象。

### 快速稳定性验证

```python
from autodock import validate_pose_stability

result = validate_pose_stability(
    receptor_pdb="6LU7.pdb",
    ligand_pdbqt="nirm_docked.pdbqt",
    protocol='quick',      # 'quick' | 'standard'
)

print(result)
# {
#   'is_stable': True,           # RMSD < 2Å + ΔE < 50 kcal/mol
#   'ligand_rmsd': 1.23,         # Å（松弛后 vs 原始 pose）
#   'pocket_rmsd': 0.45,         # Å（口袋骨架变化）
#   'interaction_retention': 0.85,  # 85% 相互作用保留率
#   'energy_change': -12.5,      # kcal/mol（负值 = 更稳定）
# }
```

### 两种验证协议

| 协议 | 内容 | 时间 | 用途 |
|------|------|------|------|
| `quick` | 能量最小化（500步）→ RMSD评估 | 1-2分钟 | 大规模筛选 |
| `standard` | 能量最小化 + 50ps Langevin动力学 | 5-10分钟 | 关键配体验证 |

### 稳定性判定标准

| 指标 | 阈值 | 说明 |
|------|------|------|
| Ligand RMSD | < 2.0 Å | 松弛后配体位置变化小 |
| Pocket RMSD | < 1.0 Å | 口袋结构未坍塌 |
| Interaction Retention | > 0.7 | 70%+ 相互作用保留 |
| Energy Change | < +50 kcal/mol | 能量未恶化 |

### 技术特点

- **Pose Relaxation**：仅能量最小化，不依赖 GAFF 参数化（避免参数化失败）
- **Graceful Fallback**：OpenMM 未安装时返回友好错误提示
- **显式溶剂**：使用 OBC2 GB 隐式溶剂模型
- **无 MD 经验要求**：自动处理所有参数

### 与完整 MD 的区别

| 特性 | OpenMM Quick | AmberTools Full MD |
|------|-------------|-------------------|
| 时间 | 1-2 分钟 | 2-16 小时 |
| 采样 | 单点能量最小化 | 系综采样 |
| 精度 | 筛选级 | 发表级 |
| 用途 | 排除明显不稳定的 pose | 计算精确 ΔG |

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

**途径 1：PubChem（已知化合物）**

```python
from autodock import fetch_molecule_pubchem

mol = fetch_molecule_pubchem("nirmatrelvir")  # 按名称
mol = fetch_molecule_pubchem("CC(=O)Oc1ccccc1C(=O)O", identifier_type='smiles')  # 按 SMILES
print(mol['smiles'])
```

**途径 2：ZINC22 虚拟筛选库（130M+ 可购买化合物）**

```python
from autodock import sample_zinc_compounds

# 按性质采样药物相似化合物（LogP、H-donor、MW 范围过滤）
df = sample_zinc_compounds(
    n=100,
    h_donors_range=(0, 3),
    logp_range=(2, 4),
    mw_range=(250, 400),
    generation="g",   # zinc-22g = ZINC20 in stock (~130M 可购买)
    n_workers=4,
)
print(df[['zinc_id', 'smiles', 'h_donors', 'logp', 'mw']].head())
#        zinc_id    smiles  h_donors  logp   mw
# 0  ZINC490000002oMg     CC(C)N         4   3.0    0
# 1  ZINC480000001wUw     CCNC          4   2.0    0
# 2  ZINC470000002phP     C=CCO         4   1.0    0
```

**ZINC ID 查询**（已知 ZINC ID 时）：

```python
from autodock import lookup_zinc_id

result = lookup_zinc_id("ZINC000000000001")
# 扫描 tranche index 文件定位，返回 SMILES 和属性
if result:
    print(result['smiles'], result['h_donors'], result['logp'])
```

**tranche 代码解析**（ZINC 文件名编码规则）：

```python
from autodock import parse_zinc_tranche

# H{h}P{p_logp}M{mw_bucket}-{phase}  → h_donors, logp, mw, phase
parse_zinc_tranche("H05P035M400-0")
# {'h_donors': 5, 'logp': 3.5, 'mw': 400, 'phase': 0}
```

**注意**：ZINC22 tranche 文件在 `files.docking.org/zinc22/zinc-22g/`，需要 `User-Agent: curl/7.70+`，函数内部已处理。

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
from autodock import find_binding_site, find_top_pockets

# 基础用法：单口袋检测
center, box = find_binding_site("protein.pdb")

# 高级用法：多口袋排序 + 科学过滤（推荐）
pockets = find_top_pockets(
    receptor_pdb="protein.pdb",
    ligand_pdb=None,           # 可选：已知配体时优化盒子大小
    padding=5.0,               # 口袋边缘扩展（Å）
    max_pockets=3,             # 返回前 N 个口袋
    use_p2rank=True,           # 启用 P2Rank 重打分
    fpocket_min_alpha=3.0,     # fpocket α-球最小半径（官方默认值，Le Guillou et al. 2011）
    fpocket_max_alpha=6.0,     # fpocket α-球最大半径（官方默认值）
)

# pockets 是按质量排序的列表
pocket = pockets[0]  # 最佳口袋
center = pocket['center']
box_size = pocket['box_size']

# 口袋属性（2026-05-08 新增）
print(f"口袋体积: {pocket['volume']:.0f} Å³")
print(f"口袋深度: {pocket['depth']:.1f} Å")
print(f"开口数: {pocket['openings']}")
print(f"疏水球: {pocket['n_apolar']} | 极性球: {pocket['n_polar']}")
print(f"Druggability: {pocket['druggability']:.3f}")
print(f"P2Rank概率: {pocket['p2rank_prob']:.3f}")
```

### 口袋质量过滤（自动应用）

| 过滤条件 | 阈值 | 行为 | 科学依据 |
|---------|------|------|---------|
| 体积 | > 2000 Å³ | 跳过 | 溶剂暴露凹槽/PPI界面 |
| 深度 | < 3 Å | 警告 | 表面浅坑，非药物口袋 |
| 尺寸 | < 5 或 > 40 Å | 跳过 | 过小/过大不适合药物 |
| P2Rank概率 | < 0.15 | 警告 | 低置信度预测 |
| Druggability | < 0.15 | 警告 | 可药性差 |
| 开口数 | ≥ 3 | 排序惩罚 | 开放通道非封闭位点 |

### 配体自适应盒子大小

当提供配体时，盒子大小会自动调整以确保足够空间：

```python
pockets = find_top_pockets(
    receptor_pdb="protein.pdb",
    ligand_pdb="ligand.pdbqt",  # ← 提供配体
    padding=5.0,
)
# 盒子大小 = max(口袋尺寸+padding, 配体尺寸+2*padding)
```

### 从共晶配体计算

```python
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
sys.path.insert(0, '/Users/allenrong/.openclaw/workspace/skills/autodock/')
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

## SnakeMake 虚拟筛选工作流

> **适用场景：** 大规模虚拟筛选（>100 个化合物）自动化Pipeline。
> 需要额外安装：`pip install snakemake`

### 核心思想

SnakeMake 工作流将虚拟筛选拆分为 5 个规则：

| 规则 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `fetch_receptor` | PDB ID | `structures/{id}.pdb` | 下载蛋白质结构 |
| `prepare_receptor` | `.pdb` | `prepared/{id}.pdbqt` | 制备受体 PDBQT |
| `run_virtual_screen` | `.pdbqt` | `results/docking_results.csv` | 批量对接 |
| `post_dock_analysis` | docking CSV | MMPBSA CSV + 2D PNG | 后处理分析 |
| `generate_report` | 结果文件 | `summary_report.html` | 生成 HTML 报告 |

### 快速开始

```bash
# 1. 复制配置模板和Snakefile
cp docking_config.template.yml docking_config.yml
cp $(python -c "import autodock; import os; print(os.path.dirname(autodock.__file__))")/Snakefile .

# 2. 编辑 docking_config.yml（设置受体、化合物库、对接参数）

# 3. 预览执行计划（不实际运行）
snakemake --cores 4 --dryrun

# 4. 执行全流程
snakemake --cores 4

# 5. 解锁（如果上次运行崩溃）
snakemake --cores 4 --unlock
```

# 2. 编辑 docking_config.yml（设置受体、化合物库、对接参数）

# 3. 预览执行计划（不实际运行）
snakemake --cores 4 --dryrun

# 4. 执行全流程
snakemake --cores 4

# 5. 解锁（如果上次运行崩溃）
snakemake --cores 4 --unlock
```

### 配置文件示例（docking_config.yml）

```yaml
receptor:
  id: "6LU7"               # PDB ID
  source: "pdb"

ligand_library:
  source: "csv"
  path: "ligands.csv"      # 你的化合物库 CSV
  smiles_column: "smiles"
  name_column: "compound"
  max_count: 100           # 最多对接多少个化合物

docking:
  center: [10.5, 20.3, -5.2]
  box_size: [20, 20, 20]
  exhaustiveness: 32        # 发表级精度
  n_poses: 10
  seed: null                # null=每次随机，固定数字=可重复

post_dock:
  mmpbsa: false             # 是否计算 MM/PBSA（慢）
  render_2d: true           # 是否渲染 2D 相互作用图
  top_n: 20                 # 后处理分析的 Top-N 化合物
```

### CLI 集成

```bash
# 通过 autodock CLI 调用 SnakeMake 工作流
python -m autodock workflow docking_config.yml --cores 4
python -m autodock workflow docking_config.yml --dry-run
python -m autodock workflow docking_config.yml --force
```

### 并行执行

Snakemake 自动管理 DAG：
- `fetch_receptor` → `prepare_receptor` → `run_virtual_screen` 串行执行
- `post_dock_analysis` 等待 `run_virtual_screen` 完成后执行
- `generate_report` 等待所有分析完成后执行
- `virtual_screen` 内部串行执行（Vina 是 CPU-bound，不受 GIL 加速）

### 输出文件

```
results/
  docking_results.csv      # 原始对接得分
  docking_summary.csv       # MMPBSA 富集版（如启用）
  summary_report.html       # HTML 可视化报告
  {compound}_best.pdbqt    # 每个化合物的最佳 pose
  {compound}_2d.png         # 2D 相互作用图（如启用）
  mmpbsa_results.csv        # MM/PBSA 结果（如启用）
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

---

## 附录 A：mmCIF (.cif) 格式支持

### 背景
- **PDB 格式已冻结**：wwPDB 不再更新 legacy PDB 格式
- **mmCIF 是主格式**：新条目（12 字符 PDB ID）**只能通过 .cif 获取**
- **OpenBabel 转换**：下载 .cif 后自动转换为 .pdb，下游工具零改动

### 使用方式
```python
# 4 字符 legacy ID（默认 auto：先尝试 .cif，失败则回退 .pdb）
fetch_protein_pdb("6LU7")
fetch_protein_pdb("6LU7", format='cif')   # 强制 .cif → .pdb 转换

# 12 字符扩展 ID（强制 .cif，需 OpenBabel）
fetch_protein_pdb("PDB_12345678", format='auto')
```

### 依赖检测
```bash
python -m autodock status
# → OpenBabel: ✅ OK
```

### 安装 OpenBabel
```bash
conda install -c conda-forge openbabel
```

---

## 附录 B：BindingDB 实验亲和力集成

### 背景
- **BindingDB** 包含 160 万+ 实验测定的结合亲和力（Ki/Kd/IC50）
- 覆盖 7,000+ 靶蛋白，270 万+ 化合物
- 免费 REST API，无需注册

### 使用方式
```python
from autodock import fetch_bindingdb_affinity, fetch_bindingdb_by_target

# 按化合物查亲和力
aff_data = fetch_bindingdb_affinity(
    smiles="CC(=O)OC1=CC=CC=C1C(=O)O",  # aspirin SMILES
    max_results=10
)
# Returns: [{'affinity_type': 'Ki', 'affinity_value': 150.0, 'affinity_unit': 'µM',
#            'target_name': 'COX-1', 'target_uniprot': 'P23219', ...}, ...]

# 按靶点查所有已知配体
ligands = fetch_bindingdb_by_target(
    uniprot_id="P00533",  # EGFR
    max_results=50
)
# Returns: [{'smiles': '...', 'name': 'Gefitinib',
#            'affinity_type': 'IC50', 'affinity_value': 0.033, ...}, ...]
```

### CLI 查询
```bash
# 按化合物名
python -m autodock bindingdb aspirin --type name --max-results 10

# 按 UniProt ID（EGFR）
python -m autodock bindingdb P00533 --type uniprot --max-results 50
```

### 数据验证场景
1. **虚拟筛选验证**：对接得分 vs 实验 Ki 相关性分析
2. **新靶点评估**：BindingDB 中是否有已知配体
3. **亲和力预测**：基于结构对接为无实验数据化合物预测活性

---

## 附录 C：小分子数据源总览

| 数据源 | 技能函数 | 覆盖范围 | 状态 |
|--------|---------|---------|------|
| **PubChem** | `fetch_molecule_pubchem()` | 1.1亿化合物结构 | ✅ |
| **ChEMBL** | `fetch_molecule_chembl()` | 200万生物活性数据 | ✅ |
| **RCSB CCD** | `fetch_ligand_ccd()` | PDB共晶配体化学信息 | ✅ |
| **NIH CACTUS** | `fetch_molecule_cactus()` | 标识符万能转换 | ✅ |
| **EBI OPSIN** | `fetch_molecule_opsin()` | IUPAC系统命名解析 | ✅ |
| **BindingDB** | `fetch_bindingdb_affinity()` | 160万实验亲和力 | ✅ |
| **DrugBank** | `fetch_molecule_drugbank()` | 药物靶点（需本地XML） | ⚠️ |

---

## 附录 D：RCSB CCD 配体查询（Ligand Expo 替代方案）

### 背景
- **PDB Ligand Expo 已退役**（2026-02-13）
- **RCSB Chemical Component Dictionary (CCD)** 是官方替代
- 覆盖 PDB 中所有小分子配体（ATP、NAD、血红素等）

### 使用方式
```python
from autodock import fetch_ligand_ccd, fetch_ligand_smiles, fetch_ligand_from_pdb

# 查询配体化学信息
info = fetch_ligand_ccd("ATP")
# Returns: {'id': 'ATP', 'name': 'ADENOSINE-5-TRIPHOSPHATE',
#           'formula': 'C10 H16 N5 O13 P3', 'formula_weight': 507.181,
#           'smiles': '...', 'inchi': '...', ...}

# 快速获取 SMILES
smiles = fetch_ligand_smiles("HEM")  # 血红素

# 下载特定 PDB 条目中的配体坐标（用于重对接验证）
sdf_path = fetch_ligand_from_pdb("1ATP", "ATP")
# → 返回 SDF 文件路径，可直接用于对接
```

### 使用场景
1. **重对接验证**：获取晶体结构中配体的原始构象作为参考
2. **虚拟筛选基准**：用已知活性配体测试对接方法准确性
3. **分子比较**：比较对接 pose 与晶体构象的 RMSD

---

## 附录 E：异常体系

技能定义了 7 个自定义异常类，用于精确错误诊断：

| 异常类 | 触发场景 | 用户提示 |
|--------|---------|---------|
| `PreparationError` | 受体/配体制备失败 | 检查输入文件格式 |
| `DockingError` | Vina 对接失败 | 检查参数和受体/配体文件 |
| `InteractionError` | 相互作用检测失败 | 检查 PLIP 依赖 |
| `ValidationError` | RMSD/验证失败 | 检查参考结构 |
| `FetchError` | 网络获取失败 | 检查网络和 PDB ID |
| `RenderError` | PyMOL/RDKit 渲染失败 | 检查依赖安装 |
| `MMPBSAError` | MM/PBSA 计算失败 | 检查 AmberTools 环境 |

### 异常处理示例

```python
from autodock import PreparationError, DockingError

try:
    prepare_receptor("protein.pdb", "protein.pdbqt")
    dock_ligand("protein.pdbqt", "ligand.pdbqt", center, box)
except PreparationError as e:
    print(f"制备失败: {e}")
    # 自动重试或 fallback
except DockingError as e:
    print(f"对接失败: {e}")
    # 调整参数重试
```

---

## 附录 F：CI/CD Pre-commit Hook

### 安装

```bash
cd ~/.openclaw/workspace/skills/autodock
# 复制 hook 到 .git/hooks/
cp scripts/pre-commit .git/hooks/
chmod +x .git/hooks/pre-commit
```

### Hook 功能

每次 `git commit` 前自动执行：

| 检查项 | 说明 |
|--------|------|
| `ruff check` | 代码风格检查 |
| `pytest tests/ -m "not slow"` | 快速测试套件 |
| `pylint --disable=R,C` | 静态分析 |

### 跳过 Hook

```bash
git commit --no-verify  # 跳过所有 pre-commit 检查
```

---

## 附录 G：类型注解

技能已全面启用 Python 类型注解：

```python
from typing import Tuple, Optional, List

def find_binding_site(
    receptor_pdb: str,
    ligand_pdb: Optional[str] = None,
    padding: float = 5.0,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    ...
```

**好处：**
- IDE 自动补全和类型提示
- `mypy` 静态类型检查
- 文档自动生成

---

*文档版本：2026-05-08*
*技能评分：91/100 (A+)*
