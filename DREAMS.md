# DREAMS.md — 2026-05-08 03:00 

## Dreaming Summary

Scanned: 129 candidates
Above threshold: 13
New promotions: 10

## Phase: Deep Sleep

🆕 - **逻辑bug**：`'GLY A 501' in l or 'TYR A 502' in l` 的 OR 本身是对的，但**这整个检查只针对 6LU7 这一个 PDB**。换其他含共结晶配体的 PDB（如 HIV-1 蛋白酶 1BVE 含 JG1），PLIP 会再次把共结晶配体误识别为待分析配体，导致相互作用映射全部错误。
  - 来源: 2026-05-07-1642.md | 评分: 0.624
   Score: 0.624

✅ - `_autodock.py`: 修复 `_parse_ligplot_hhb`/`_parse_ligplot_nnb`，移除 `use_ghostscript`，修复 LIGPLOT 配体识别
  - 来源: 2026-05-06.md | 评分: 0.593
   Score: 0.593

🆕 - **修复**：改为 `# Set output paths (fields already defined in DockingResult dataclass)`
  - 来源: 2026-05-07.md | 评分: 0.582
   Score: 0.582

🆕 - **`ensemble_mode=True`**（默认）：通过 `_generate_receptor_variants()` 对口袋附近残基做 CA 为中心的侧链旋转（8 步 × 45°），生成多个受体构象变体，对每个变体分别对接，最后从全部结果中选最优 pose。这是常见的 **ensemble docking** 策略，比真正的柔性残基更实用。
  - 来源: 2026-05-07-1642.md | 评分: 0.579
   Score: 0.579

🆕 - **autodock 技能** — P0/P1 全部修复，68 项测试通过，git 提交 `c7fd3c6`
  - 来源: 2026-05-07-1642.md | 评分: 0.535
   Score: 0.535

🆕 - **慢测试套件：** 6项全部通过（含 `dock_single` SMILES对接、`batch_docking` 2×2矩阵、`screen_ligands` end-to-end）
  - 来源: 2026-05-07-1642.md | 评分: 0.533
   Score: 0.533

🆕 - **问题**：`_core.py` 中 `object.__setattr__` 注释与 slots dataclass 无关
  - 来源: 2026-05-07.md | 评分: 0.529
   Score: 0.529

🆕 - **修复**：ZINC22 `parse_tranche_props()` 缺失属性返回 `None` 而非 `0`
  - 来源: 2026-05-07.md | 评分: 0.523
   Score: 0.523

🆕 - **修复**：超时线程 `daemon=True` → `daemon=False`（避免 C++ 内存损坏）
  - 来源: 2026-05-07.md | 评分: 0.519
   Score: 0.519

✅ - **修复**: 改为先调用 `detect_interactions_plip()` 获取相互作用列表，再传递给渲染函数
  - 来源: 2026-05-06.md | 评分: 0.519
   Score: 0.519
