# Autodock Skill 数据源配置检查报告

**日期：** 2026-05-07

---

## 一、蛋白结构数据源

| 数据源 | 状态 | URL/配置 | 说明 |
|--------|------|---------|------|
| **RCSB PDB** | ✅ 正常 | `https://files.rcsb.org/download/{pdb_id}.pdb` | 主数据源，自动缓存 |
| **AlphaFold DB** | ✅ 正常 | `https://alphafold.ebi.ac.uk/files/AF-{uid}-F1-model_v6.pdb` | v6 版本有效 |
| **SWISS-MODEL** | ✅ 正常 | `https://swissmodel.expasy.org/repository/uniprot/{uid}.json` | API 可访问 |
| **PDB-REDO** | ✅ 正常 | `https://pdb-redo.eu/db/{pdb_id}/{pdb_id}_final.pdb` | 不支持 HEAD，GET 正常 |

**自动回退链：**
```
PDB ID 给定 → RCSB PDB → PDB-REDO → AlphaFall (需 UniProt)
UniProt 给定 → AlphaFold → SWISS-MODEL
```

---

## 二、小分子数据源

| 数据源 | 状态 | URL/配置 | 说明 |
|--------|------|---------|------|
| **PubChem** | ✅ 正常 | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/...` | PUG REST API，支持 name/SMILES/CID |
| **ChEMBL** | ✅ 正常 | `https://www.ebi.ac.uk/chembl/api/data/molecule/...` | REST API，支持 ID/名称搜索 |
| **OPSIN (Cactus)** | ⚠️ 有限 | `https://www.ebi.ac.uk/opsin/ws/{name}.smi` | **仅支持 IUPAC 名称**，不支持常见名 |
| **DrugBank** | ❌ 已停用 | 无 | 公开 API 已关闭，函数内正确抛异常 |

---

## 三、问题与建议

### 1. OPSIN (Cactus) — 使用限制 ⚠️

**现状：**
- IUPAC 名称：`2-acetoxybenzoic acid` → ✅ 正确解析
- 常见名：`aspirin` → ❌ 解析失败
- `caffeine` / `glucose` → ❌ 同样失败

**影响：**
`fetch_molecule_cactus()` 和 `fetch_molecule(source='cactus')` 对常见药物名称不可用。

**建议：**
- 文档中明确标注 "IUPAC names only"
- 或增加 PubChem fallback：OPSIN 失败时自动尝试 PubChem

### 2. ChEMBL HEAD 请求 405 — 无影响 ✅

**现状：** `curl -I` (HEAD) 返回 405，但代码中使用 GET，实际正常。

### 3. PDBredo HEAD 请求 404 — 无影响 ✅

**现状：** `curl -I` (HEAD) 返回 404，但 GET 正常。代码中使用 `urllib.request.urlretrieve` (GET)。

---

## 四、配置评估

| 评估项 | 评分 | 说明 |
|--------|------|------|
| 数据源覆盖 | ⭐⭐⭐⭐⭐ | 4 蛋白源 + 3 小分子源 |
| 自动回退 | ⭐⭐⭐⭐⭐ | `source='auto'` 智能回退 |
| 缓存机制 | ⭐⭐⭐⭐⭐ | `~/.openclaw/structures_cache/` |
| SDF 质量 | ⭐⭐⭐⭐ | PubChem 大分子 SDF 截断 → RDKit ETKDGv3 fallback |
| 错误处理 | ⭐⭐⭐⭐ | 各函数有 try/except，但部分用裸 `except Exception` |
| 文档注释 | ⭐⭐⭐⭐ | DrugBank 停用说明清晰 |

---

## 五、是否需要修复？

| 问题 | 优先级 | 建议 |
|------|--------|------|
| OPSIN 常见名失败 | 🟡 P1 | 文档标注 + PubChem fallback |
| `_database.py` 属性解析 `None` | ✅ 已修复 | PR #2 |
| 裸 `except Exception` | ⚠️ P2 | 逐步细化异常类型 |

**结论：** 数据源配置整体合理，核心功能全部可用。仅需完善 OPSIN 使用说明。
