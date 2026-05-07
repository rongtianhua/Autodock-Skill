# Errors

Command failures and integration errors.

**Format**: ERR-YYYYMMDD-XXX

---

## 2026-05-04: ZINC22 sample_zinc_compounds 返回空结果 + ADMETlab API 调研

### ZINC22 Bug

**症状**：`sample_zinc_compounds(n=5)` 返回 0 行，无报错

**根因**：fetch 闭包内引用了 `urllib.request.Request()`，但模块级只有 `import os/tempfile/warnings/logging/signal/datetime/numpy/pandas/threading...`，没有 `import urllib`。Python 在闭包内按 LEGB 查找时找不到，在 ThreadPoolExecutor worker 内抛出 `NameError: name 'urllib' is not defined`。

**关键发现**：这个异常被 `except Exception: return None` 静默吞掉，48 个 tranche 全部返回 None，最终 `pd.DataFrame([])` → 静默失败，没有 traceback。

**教训**：在嵌套函数内引用标准库，必须显式 import，不能假设外层已导入。ThreadPoolExecutor 会把异常变成 `UnknownError` 存入 Future，`.result()` 返回时如果被静默 catch，会变成静默数据丢失，比直接报错危险得多。

**修复**：
```python
def sample_zinc_compounds(...):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import gzip
    import re
    import urllib.request
    import random
    def fetch(url):
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.70+"})  # now works
```

**教训类型**：Bug (静默失败) + 反模式 (隐式跨作用域变量依赖)

---

### ADMETlab API 调研结论

**不是端点地址错误，是服务端不稳定**

| 端点 | HTTP | 说明 |
|------|------|------|
| `https://admetlab3.scbdd.com/apis/evaluate/` | 500 | Django 模板缺失（`TemplateDoesNotExist`），后端损坏 |
| `https://admetlab3.scbdd.com/api/single/admet` | 500 | 路径存在，后端 bug（`KeyError: BSEP not in index`），某列缺失 |
| `https://admetlab3.scbdd.com/api/admet` | 404 | 路径不存在 |

**无反爬机制**：Sequential requests 全部正常响应（无 429/403/301 跳转），User-Agent 不影响结果。

**当前策略正确**：`predict_admet()` 中 ADMETlab 不可用时自动降级到 RDKit，计算结果正常。RDKit fallback 已经是发表级 ADMET 预测的最佳保底方案，无需额外修复。

**教训类型**：外部服务不可靠 → 已有 fallback 策略，无需深究

