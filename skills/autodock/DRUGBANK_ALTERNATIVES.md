# DrugBank 数据库替代方案调研报告

**日期：** 2026-05-07

---

## 一、DrugBank 现状

| 项目 | 状态 |
|------|------|
| **最新版本** | 5.1.20（2026-05-06） |
| **公开 API** | ❌ 已关闭（需付费订阅） |
| **学术下载** | ⚠️ 暂时暂停（"temporarily paused while we update how we distribute data"） |
| **数据格式** | XML（193MB）、SDF（11MB） |
| **许可** | CC BY-NC 4.0（非商业） |
| **获取方式** | 注册免费学术账户 → curl 下载（需 EMAIL:PASSWORD） |

---

## 二、可用替代方案

### 方案 1：PubChem 交叉引用（推荐）✅

**原理：** PubChem 收录了几乎所有 DrugBank 化合物的交叉引用（XRef）。

**调用方式：**
```python
# PubChem PUG REST 获取 DrugBank ID 交叉引用
url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{drug_name}/xrefs/DrugBank/JSON"

# 返回示例：
# {"InformationList": {"Information": [{"DrugBank": ["DB00945"]}]}}
```

**优点：**
- 完全免费，无需注册
- 实时更新
- 支持常见名搜索

**局限：**
- 只能获取 DrugBank ID，无法获取详细属性（靶点、相互作用等）
- 需要二次查询其他数据库获取完整信息

---

### 方案 2：ChEMBL 交叉引用 ✅

**原理：** ChEMBL 也收录了 DrugBank ID 映射。

**调用方式：**
```python
# ChEMBL API 搜索药物，返回中包含 cross_references
url = f"https://www.ebi.ac.uk/chembl/api/data/molecule?pref_name__iexact={drug_name}"
# 返回字段：cross_references → 包含 DrugBank ID
```

**优点：**
- 免费学术 API
- 包含生物活性数据（IC50/Ki 等）
- 有药物靶点信息

---

### 方案 3：本地 DrugBank XML 解析（离线）⚠️

**前提：** 用户已下载 DrugBank XML dump（需学术账户）

**技术路线：**
```python
import xml.etree.ElementTree as ET

def parse_drugbank_xml(xml_path, drugbank_id):
    """从本地 DrugBank XML 解析特定药物信息。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    ns = {'db': 'http://www.drugbank.ca'}
    
    for drug in root.findall('db:drug', ns):
        db_id = drug.find('db:drugbank-id', ns)
        if db_id is not None and db_id.text == drugbank_id:
            name = drug.find('db:name', ns).text
            smiles = drug.find('.//db:smiles', ns)
            # ... 提取靶点、相互作用等
            return {'name': name, 'smiles': smiles.text if smiles else None}
    return None
```

**优点：**
- 完全离线，不依赖网络
- 可获取完整 DrugBank 数据（靶点、通路、相互作用）

**局限：**
- 需要先下载 193MB XML
- 学术下载当前暂停
- 需要解析 XML，速度较慢

---

### 方案 4：第三方数据镜像/聚合服务

| 服务 | 类型 | 说明 |
|------|------|------|
| **RxLabelGuard** | 商业 API | 基于 FDA 药物相互作用数据 |
| **DrugsAPI** | 商业 API | DrugBank 替代方案，有免费层 |
| **Kaggle 历史 dump** | 静态数据 | DrugBank 5.1.10 CSV（3年前） |
| **ChEMBL** | 学术数据库 | 包含药物-靶点数据，可替代大部分 DrugBank 功能 |

---

## 三、对我们技能的建议

### 当前状态评估

```python
def fetch_molecule_drugbank(drugbank_id=None, drug_name=None):
    """
    Fetch small molecule from DrugBank.

    Note: DrugBank 已停止公开API（需注册+付费Key）。
    本函数通过 PubChem 代理提供 DrugBank 名称搜索。
    若需完整 DrugBank 数据，请使用 PubChem 或 ChEMBL。
    """
```

当前实现：**合理**。正确识别了公开 API 关闭的事实，并引导用户使用 PubChem/ChEMBL。

### 可选增强

#### 增强 1：PubChem → DrugBank ID 查询
```python
def get_drugbank_id_via_pubchem(drug_name: str) -> str | None:
    """通过 PubChem 交叉引用获取 DrugBank ID。"""
    # 实现上述方案 1
```

#### 增强 2：本地 DrugBank XML 支持
```python
def load_local_drugbank(xml_path: str):
    """加载本地 DrugBank XML，提供离线查询能力。"""
    # 实现上述方案 3
```

#### 增强 3：ChEMBL 靶点信息替代
```python
def fetch_drug_targets_chembl(drug_name: str) -> dict:
    """通过 ChEMBL 获取药物靶点信息（替代 DrugBank 靶点数据）。"""
    # 调用 ChEMBL API 获取靶点、生物活性
```

---

## 四、结论

| 需求 | 推荐方案 |
|------|---------|
| 药物 SMILES/结构 | **PubChem**（已有） |
| 药物靶点信息 | **ChEMBL** |
| DrugBank ID 查询 | **PubChem XRef** |
| 完整 DrugBank 数据（离线） | 等待学术下载恢复后解析 XML |
| 药物相互作用 | RxLabelGuard / DrugsAPI（商业） |

**短期建议：** 保持当前实现（PubChem/ChEMBL fallback），无需改动。DrugBank 公开 API 确实已不可恢复。

**长期建议：** 如果用户需要 DrugBank 特有的数据（如药物-食物相互作用、药物-酶关系），可以考虑：
1. 注册 DrugBank 学术账户，下载 XML
2. 在技能中增加本地 XML 解析模块
3. 用 PubChem/ChEMBL 交叉引用作为在线 fallback

---

## 参考链接

- DrugBank 下载页面：https://go.drugbank.com/releases/latest
- PubChem PUG REST：https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
- ChEMBL API：https://www.ebi.ac.uk/chembl/api/data/docs
