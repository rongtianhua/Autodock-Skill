# ClawBio Skills Python 代码修复指南

## 1. 相对导入修复

### 问题
`gwas_lookup/` 是普通目录，相对导入 `from ..api` 语法错误。

### 修复

**文件: `gwas_lookup/__init__.py`**

```python
# 添加空的 __init__.py 使其成为合规 Python 包
```

**文件: `gwas_lookup/some_module.py`**

```python
# 修改前
from ..api import some_function

# 修改后
from api import some_function
```

## 2. Subprocess PYTHONPATH 修复

### 问题
`clawbio.py` 的 `run_skill` 函数使用 `os.environ.copy()`，导致 PYTHONPATH 在子进程中丢失。

### 修复

在 subprocess 调用中显式设置 PYTHONPATH：

```python
import os
import subprocess

def run_skill(skill_name, args):
    skill_dir = "/path/to/skills"
    root_dir = "/path/to/clawbio"
    
    # 获取用户 site-packages 路径
    import site
    user_packages = site.getusersitepackages()
    
    # 构建完整 PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{skill_dir}:{root_dir}:{user_packages}"
    
    # 执行子进程
    subprocess.Popen(
        ["python", script],
        env=env,
        ...
    )
```

## 3. Shebang 修复

### 问题
`methylation-clock` 的 shebang 指向系统 Python 而非 conda 环境。

### 修复

```python
#!/Users/user/miniconda3/envs/pyaging/bin/python
```

## 4. 执行权限修复

### 问题
`methylation_clock.py` 缺少执行权限。

### 修复

```bash
chmod +x methylation_clock.py
```

## 验证清单

- [ ] 所有 skill 目录包含 `__init__.py`
- [ ] 使用绝对导入而非相对导入
- [ ] subprocess 调用显式传递 PYTHONPATH
- [ ] shebang 指向正确的 Python 解释器
- [ ] 脚本文件具有执行权限 (`chmod +x`)

## 调试技巧

```python
# 在子进程启动时打印 PYTHONPATH
env["PYTHONPATH"] = f"{skill_dir}:{root_dir}:{user_packages}"
print(f"PYTHONPATH: {env['PYTHONPATH']}")
```