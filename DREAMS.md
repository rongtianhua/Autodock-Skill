# DREAMS.md — 2026-05-07 09:55 

## Dreaming Summary

Scanned: 95 candidates
Above threshold: 18
New promotions: 11

## Phase: Deep Sleep

✅ - 修复1：`_docking.py` 顶部添加导入：`from autodock._interactions import ..., render_interactions_2d; from autodock._rendering_3d import render_scene`
  - 来源: 2026-05-07.md | 评分: 0.709
   Score: 0.709

✅ - 修复：在 `_core.py` 的 `DockingResult` 中添加三个字段 `png_2d: str | None = None; png_3d: str | None = None; output_dir: str | None = None`
  - 来源: 2026-05-07.md | 评分: 0.636
   Score: 0.636

✅ - 修复：重构 `prepare_receptor_with_waters` — 在 meeko 调用**之前**预过滤 skip_linkers={'02J','010','PJE','NFH','NFN'}，保留 HOH/WAT/H2O
  - 来源: 2026-05-07.md | 评分: 0.625
   Score: 0.625

✅ - `_autodock.py`: 修复 `_parse_ligplot_hhb`/`_parse_ligplot_nnb`，移除 `use_ghostscript`，修复 LIGPLOT 配体识别
  - 来源: 2026-05-06.md | 评分: 0.597
   Score: 0.597

✅ - 根因：6LU7 含 02J/010/PJE linker 残基，`allow_bad_res=True` 对 bonded unknown residues（linker）无效
  - 来源: 2026-05-07.md | 评分: 0.589
   Score: 0.589

🆕 - 根因：`@dataclass(slots=True)` 的 `DockingResult` 没有 `__dict__`，`dr.png_2d = ...` 报错
  - 来源: 2026-05-07.md | 评分: 0.549
   Score: 0.549

🆕 - 根因：`render_scene` 的第一个参数是 `pdb_path`，而 `dock_single` 用 `receptor_pdb=`
  - 来源: 2026-05-07.md | 评分: 0.537
   Score: 0.537

🆕 - 关键发现：`object.__setattr__` 对 `slots=True` dataclass 也无效（与普通 class 不同）
  - 来源: 2026-05-07.md | 评分: 0.535
   Score: 0.535

✅ - 为 π-π (pistacking) 新增独立分支：用 `item.proteinring.center` 设置 `prot_center`（protein ring centroid），存入 `_prot_center`，后续 nearest-atom fallback 不覆盖
  - 来源: 2026-05-05.md | 评分: 0.530
   Score: 0.530

🆕 - **修复**: 改为先调用 `detect_interactions_plip()` 获取相互作用列表，再传递给渲染函数
  - 来源: 2026-05-06.md | 评分: 0.522
   Score: 0.522
