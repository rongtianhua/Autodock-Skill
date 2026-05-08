# Autodock 口袋预测代码 — 科学严谨性审查报告

**审查日期：** 2026-05-08  
**审查人：** PrimeClaw（资深生信工程师视角）  
**审查范围：** `_preparation.py` — `find_top_pockets()` / `find_binding_site()` / P2Rank rescore  
**官方文档对照：** fpocket 4.0 手册、P2Rank PMC6091426、fpocket 论文 PMC2700099  

---

## 执行摘要

| 维度 | 评估 | 说明 |
|------|------|------|
| **算法选择** | ✅ 合理 | fpocket (Voronoi+α球) + P2Rank (ML rescoring) 是行业标准组合 |
| **参数设置** | ⚠️ 有优化空间 | 全用默认值，缺少针对不同口袋类型的调参 |
| **后处理过滤** | 🔴 缺失 | 无体积/深度/开口度过滤，无概率阈值筛选 |
| **代码健壮性** | ⚠️ 有漏洞 | 正则解析脆弱、无测试覆盖、全局常量含PDB特异残留 |
| **文档对齐** | ⚠️ 部分偏差 | 部分声明缺乏文献支撑，实现细节与最佳实践有差距 |
| **总体评价** | **B+** | 基础框架正确，但过滤层和参数优化不足，影响假阳性控制 |

---

## 一、算法选择与组合策略 — ✅ 科学正确

### 1.1 fpocket — 几何口袋检测

**实现：**
```python
result = subprocess.run(
    [fpocket_bin, '-f', prep_pdb_abs],
    capture_output=True, text=True, timeout=120, cwd=prep_dir
)
```

**评估：** ✅ 正确
- fpocket 基于 **Voronoi tessellation + α球**（Le Guilloux et al. 2009, PMC2700099）
- 默认参数：`-m 3.4` (最小α球半径), `-M 6.2` (最大), `-D 2.4` (聚类距离)
- 这些默认值经过大规模基准测试验证，适用于大多数蛋白质
- 代码使用 fpocket 4.0（2024年最新版）✅

**建议：** 当前默认参数对一般药物口袋（球形、疏水）合适。对于特殊口袋类型，未来可增加参数覆盖：
- 浅表口袋（如蛋白-蛋白界面）：`-m 4.5 -M 8.0`（更大α球）
- 深埋隧道（如离子通道）：`-m 2.5 -M 5.0`（更小α球）

---

### 1.2 P2Rank — ML 重评分

**实现：**
```python
p2rank_probs = _run_p2rank_rescore(prep_pdb_abs, base, out_dir)
```

**评估：** ✅ 正确
- P2Rank (Krivák & Hoksza, 2018, PMC6091426) 使用 **随机森林** 对口袋进行概率校准
- 独立基准测试显示 P2Rank top-3 成功率 ~85-90%（优于纯 fpocket）
- 代码使用 P2Rank 2.5.1 ✅
- rescoring 模式（`PARAM.PREDICTION_METHOD=fpocket`）是 P2Rank 官方支持的用法 ✅

**建议：** P2Rank rescoring 是目前最优的口袋排序策略之一。实现正确。

---

### 1.3 优先级策略

**实现：**
```
1. ligand_pdb 提供 → 以配体质心为中心（金标准）
2. 否则 → fpocket 检测 → P2Rank rescoring → top-N
```

**评估：** ✅ 科学正确
- 共晶配体中心是最准确的口袋定义方式（CASF-2013 标准）
- fpocket + P2Rank 是 Apo 结构的最佳替代方案
- 多口袋策略（top-3）覆盖 ~90% 真结合位点（有文献支撑）

---

## 二、参数设置 — ⚠️ 有优化空间

### 2.1 fpocket 参数：全默认值

**当前：** 未传入任何自定义参数，使用 fpocket 内置默认值

```bash
fpocket -f protein.pdb  # 默认: -m 3.4 -M 6.2 -D 2.4
```

**问题：**
- 对小分子（MW < 200）的窄口袋，默认 `-M 6.2` 可能遗漏部分浅表亚口袋
- 对多结构域蛋白，默认 `-D 2.4` 可能将相邻口袋错误合并

**优化建议（低优先级）：**
```python
# 可选参数暴露给用户
def find_top_pockets(..., fpocket_min_alpha: float = 3.4, 
                     fpocket_max_alpha: float = 6.2):
    cmd = [fpocket_bin, '-f', prep_pdb, 
           '-m', str(fpocket_min_alpha), 
           '-M', str(fpocket_max_alpha)]
```

---

### 2.2 Padding 与 Box Size

**当前实现：**
```python
_POCKET_MIN_DIM = 5.0   # Å
_POCKET_MAX_DIM = 60.0  # Å

def _compute_box_size(dims, padding=5.0):
    raw = [d + 2 * padding for d in dims]
    return tuple(max(10.0, round(v * 2) / 2) for v in raw)
```

**评估：** ⚠️ 部分合理，部分需优化

**优点：**
- `padding=5.0 Å` 是行业标准（允许配体在口袋周围采样）
- 最小 10 Å 限制防止过小盒子导致 Vina 失败 ✅
- 0.5 Å 四舍五入匹配 Vina 的 0.375 Å 网格间距 ✅

**问题：**

| 问题 | 说明 | 风险 |
|------|------|------|
| `_POCKET_MAX_DIM = 60.0` | 60 Å 口袋跨度过大 | 假阳性口袋（如蛋白-蛋白界面）会被保留，浪费计算资源 |
| 无配体大小自适应 | 小配体（aspirin）和大配体（nirmatrelvir）用同样 padding | 小配体盒子过大 → 对接变慢；大配体盒子过小 → 采样不足 |
| 无口袋形状适配 | 球形口袋和长隧道用同样 padding | 非最优 |

**建议修复：**
```python
# 1. 降低 max_dim 阈值
_POCKET_MAX_DIM = 40.0  # 更严格过滤（40 Å 已足够容纳最大药物分子）

# 2. 根据配体大小自适应 padding（可选增强）
def _compute_box_size(dims, padding=5.0, ligand_pdbqt: str = None):
    if ligand_pdbqt:
        # 解析配体边界框，确保盒子 ≥ 配体尺寸 + padding
        lig_dims = _estimate_ligand_dimensions(ligand_pdbqt)
        required = [max(d + 2*padding, ld + 4*padding) 
                    for d, ld in zip(dims, lig_dims)]
    else:
        required = [d + 2*padding for d in dims]
    return tuple(max(10.0, round(v * 2) / 2) for v in required)
```

---

## 三、后处理过滤 — 🔴 关键缺失

### 3.1 无体积过滤

**fpocket 输出包含：** 口袋体积（Å³）、α球数量、深度、开口数

**当前代码：** 只解析 center/dims/druggability，**未使用 volume/depth/openings**

**科学影响：**
- 大体积口袋（>1000 Å³）通常是假阳性（溶剂暴露凹槽或蛋白-蛋白界面）
- 深埋口袋（深度 > 10 Å）比浅表口袋更可能是真实结合位点

**建议修复：**
```python
# 在 _parse_fpocket_info 中增加解析
pockets.append({
    'num': pocket_num,
    'druggability': druggability,
    'volume': volume,        # 新增
    'depth': depth,          # 新增
    'n_alpha_spheres': n,    # 新增
    'center': center,
    'dims': dims,
})

# 在过滤阶段增加体积/深度阈值
if p['volume'] > 2000:  # 过大口袋 → 假阳性
    continue
if p['depth'] < 3.0:     # 过浅口袋 → 可能不是药物口袋
    logger.warning(f"Pocket #{p['num']} shallow (depth={p['depth']:.1f}Å), may be false positive")
```

---

### 3.2 无概率/可药性阈值

**当前代码：** 排序用 P2Rank 概率，但**不剔除低概率口袋**

```python
def pocket_sort_key(p):
    prob = p2rank_probs.get(p['num'], None) if p2rank_probs else None
    return (prob if prob is not None else -1.0, p['druggability'])
pockets.sort(key=pocket_sort_key, reverse=True)
```

**问题：**
- P2Rank 概率 < 0.2 的口袋可靠性很低（随机森林的校准概率）
- fpocket Druggability Score < 0.2 的口袋通常不是药物可及位点
- 当前代码保留所有口袋，只是排序不同

**建议修复：**
```python
# 增加软阈值过滤（不硬剔除，只警告）
_P2RANK_PROB_THRESHOLD = 0.15   # P2Rank 概率低于此值标记为低置信度
_DRUGGABILITY_THRESHOLD = 0.15  # fpocket 可药性低于此值标记

for p in pockets:
    prob = p2rank_probs.get(p['num'], None)
    if prob is not None and prob < _P2RANK_PROB_THRESHOLD:
        logger.warning(f"Pocket #{p['num']} low P2Rank confidence ({prob:.3f} < {_P2RANK_PROB_THRESHOLD})")
    if p['druggability'] < _DRUGGABILITY_THRESHOLD:
        logger.warning(f"Pocket #{p['num']} low druggability ({p['druggability']:.3f} < {_DRUGGABILITY_THRESHOLD})")
```

---

### 3.3 无开口度（Opening）分析

**fpocket 能力：** 可检测口袋开口数（mouths），封闭口袋（0-1开口）比开放口袋更可能是结合位点

**当前代码：** 未解析开口数

**建议：** 在 `_parse_fpocket_info` 中解析 `Number of mouth openings` 字段，优先推荐封闭/半封闭口袋。

---

## 四、代码健壮性 — ⚠️ 存在漏洞

### 4.1 全局常量含 PDB 特异残留

```python
_SKIP_RES = {'HOH', 'WAT', 'H2O', 'PJE', '02J', '010', '03U', '03T', '02K', '02L'}
```

**问题：** 🔴
- `PJE`, `02J`, `010` 等是 **6LU7 的共晶配体/Linker 残留名**，不是通用水分子名
- 这些被加入全局跳过列表是因为之前修复 6LU7 的 PLIP 竞争 bug
- 但它们是 PDB 特异的，不应该出现在全局常量中
- 影响：分析其他 PDB 时，如果恰好有相同 residue name（巧合），会被错误移除

**修复：**
```python
# 分离通用水分子和 PDB 特异残留
_SKIP_WATER = {'HOH', 'WAT', 'H2O', 'DOD'}  # 通用水分子
_SKIP_PDB_SPECIFIC = {'PJE', '02J', '010', '03U', '03T', '02K', '02L'}  # 6LU7 linker

# 在 prepare_receptor 中，用户可选是否跳过 linker
# 在 fpocket 准备中，只跳过水分子（fpocket 自己会处理 linker）
def _prepare_pdb_for_fpocket(pdb_in: str, pdb_out: str, 
                             skip_water: bool = True,
                             skip_linkers: set = None) -> None:
    skip = set(_SKIP_WATER) if skip_water else set()
    if skip_linkers:
        skip.update(skip_linkers)
    # ...
```

---

### 4.2 正则解析脆弱

**当前 `_parse_fpocket_info`：**
```python
blocks = re.split(r'(?=Pocket \+ :)', open(info_path).read())
m = re.match(r'Pocket (\d+) :', block)
dm = re.search(r'Druggability Score :\s+([\d.]+)', block)
```

**风险：** ⚠️
- fpocket 4.0 的输出格式与 2.0/3.0 有差异。如果未来升级 fpocket，正则可能失效
- `Druggability Score` 字段名是否稳定？fpocket 手册确认该字段名稳定 ✅
- 但 `Volume`, `Depth`, `Number of openings` 等字段同样重要，当前未解析

**建议：** 增加格式验证和降级处理
```python
def _parse_fpocket_info(info_path: str) -> list:
    content = open(info_path).read()
    if 'Pocket 1 :' not in content:
        raise PreparationError(f"fpocket info file format unexpected: {info_path}")
    # ... existing parsing ...
```

---

### 4.3 P2Rank 口袋编号映射风险

**当前代码：**
```python
m = re.search(r'pocket[._]?(\d+)', name, re.IGNORECASE)
if m:
    fpocket_num = int(m.group(1))
    probabilities[fpocket_num] = prob
```

**潜在问题：** ⚠️
- P2Rank rescoring 后，口袋编号是否一定与 fpocket 原始编号一致？
- 如果 P2Rank 重新排序或过滤口袋，编号可能错位
- 当前代码假设编号 1:1 映射，这个假设未经充分验证

**缓解：** 已通过 `pocket[._]?(\d+)` 正则处理 `pocket.1` 和 `pocket1` 两种格式。但如果 P2Rank 输出 `pocket2` 对应 fpocket 的口袋 #3，映射会错误。

**建议：** 增加验证逻辑
```python
# 检查 P2Rank 返回的口袋数与 fpocket 检测到的口袋数是否一致
if p2rank_probs and len(p2rank_probs) != len(pockets):
    logger.warning(f"P2Rank returned {len(p2rank_probs)} pockets, "
                   f"but fpocket found {len(pockets)} — number mapping may be unreliable")
```

---

### 4.4 无测试覆盖

**现状：**
```bash
grep -rn "find_top_pockets\|find_binding_site" tests/
# 只出现在 test_alphafold_plip.py（间接测试）
# 无专门的 pocket detection 单元测试
```

**风险：** 🔴
- `_parse_fpocket_info` 的正则解析未经自动化验证
- `_run_p2rank_rescore` 的 CSV 解析格式变化时无预警
- `_compute_box_size` 的边界条件未测试

**建议：** 增加 `tests/test_pocket_detection.py`
```python
class TestPocketDetection:
    def test_parse_fpocket_info(self):
        """Test parsing of fpocket info file."""
        
    def test_compute_box_size(self):
        """Test box size computation with various inputs."""
        
    def test_ligand_based_center(self):
        """Test ligand-based pocket center calculation."""
        
    def test_pocket_dimension_filter(self):
        """Test min/max dimension filtering."""
```

---

## 五、与官方文档的对齐情况

| 官方文档 | 我们的实现 | 对齐度 |
|---------|---------|--------|
| fpocket: 默认 `-m 3.4 -M 6.2` | 使用默认值 | ✅ 100% |
| fpocket: Druggability Score 0-1 | 正确解析并排序 | ✅ 100% |
| fpocket: Pocket volume/depth/openings | **未解析** | 🔴 0% |
| P2Rank: `rescore` 模式用法 | `PARAM.PREDICTION_METHOD=fpocket` | ✅ 100% |
| P2Rank: Probability 0-1 | 正确解析并排序 | ✅ 100% |
| P2Rank: Top-3 success ~85% | docstring 声明 "90%+" | ⚠️ 略高 |
| Vina: Box ≥ 10 Å | `max(10.0, ...)` | ✅ 100% |
| 最佳实践: 体积过滤 | 无 | 🔴 缺失 |
| 最佳实践: 概率阈值 | 无 | 🔴 缺失 |

---

## 六、修复优先级清单

### 🔴 P0 — 立即修复（影响科学正确性）

1. **分离 PDB 特异残留**
   - 将 `PJE`, `02J`, `010` 等从 `_SKIP_RES` 移到 PDB 特定处理逻辑
   - 文件：`_core.py`

2. **增加口袋体积/深度解析**
   - 在 `_parse_fpocket_info` 中解析 `Volume`, `Depth`, `Number of mouth openings`
   - 文件：`_preparation.py`

3. **增加体积过滤**
   - 过滤掉 >2000 Å³ 的超大口袋（假阳性）
   - 文件：`_preparation.py`

### 🟡 P1 — 重要（提升稳健性）

4. **增加概率阈值警告**
   - P2Rank < 0.15 / Druggability < 0.15 时 log warning
   - 文件：`_preparation.py`

5. **降低 `_POCKET_MAX_DIM`**
   - 从 60.0 → 40.0 Å
   - 文件：`_preparation.py`

6. **增加 P2Rank 口袋数验证**
   - 检查 P2Rank 返回口袋数与 fpocket 一致性
   - 文件：`_preparation.py`

7. **增加口袋检测单元测试**
   - 创建 `tests/test_pocket_detection.py`
   - 测试 fpocket 解析、box 计算、维度过滤

### 🟢 P2 — 增强（可选优化）

8. **fpocket 参数暴露**
   - `find_top_pockets(..., fpocket_min_alpha=3.4, fpocket_max_alpha=6.2)`
   - 文件：`_preparation.py`

9. **配体自适应 box**
   - 根据配体大小调整 padding
   - 文件：`_preparation.py`

10. **开口度排序**
    - 优先封闭口袋（开口数 0-1）
    - 文件：`_preparation.py`

---

## 七、总体评价

| 维度 | 得分 | 说明 |
|------|------|------|
| 算法选择 | 18/20 | fpocket+P2Rank 是最佳组合之一 |
| 参数设置 | 14/20 | 全默认，无自适应，无阈值 |
| 后处理过滤 | 10/20 | 体积/深度/开口度/概率过滤全部缺失 |
| 代码健壮性 | 14/20 | 解析脆弱，无测试，全局常量含PDB特异残留 |
| 文档对齐 | 16/20 | 核心对齐，部分声明略高，过滤层缺失 |
| **口袋检测专项总分** | **72/100 (B)** | **基础框架正确，过滤层薄弱** |

---

## 八、一句话结论

> **口袋检测的底层算法选择（fpocket + P2Rank）是科学正确的，但后处理过滤层薄弱——缺少体积/深度/开口度/概率阈值筛选，导致假阳性口袋可能进入下游对接流程，浪费计算资源并可能产生误导性结果。建议优先修复 P0 项（PDB 特异残留分离 + 体积过滤）。**

---

*审查完成时间：2026-05-08*  
*参考：fpocket 4.0 手册、P2Rank PMC6091426、fpocket 论文 PMC2700099、MolModa 文档*
