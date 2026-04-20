# macOS R 环境配置参考

## conda R vs Homebrew R 核心区别

| 对比维度 | conda R (`r-base`) | Homebrew R |
|---------|-------------------|------------|
| **版本** | R 4.4.2 | R 4.5.3 (更新) |
| **编译器** | conda 自己的 gcc/libgfortran | Apple Clang + Homebrew gcc |
| **Java 路径** | conda 自带 Java 配置 | Homebrew OpenJDK + 系统路径 |
| **包安装方式** | `install.packages()` 从 CRAN 源码编译 | 同上 |
| **rJava 编译** | ❌ conda 编译器链难找 JNI | ✅ Homebrew 自带完整工具链 |
| **libgfortran** | ❌ 依赖链容易损坏 | ✅ 正常 |

## conda r-base 适用场景

- Python 脚本里 `reticulate` 桥接 R
- conda 环境里的 R 工具（如某些 Bioconductor workflow 需要 R）
- 轻量 R 脚本（不需要重型包）

**不适合场景：** 完整生物医学数据分析、GEOquery/biomaRt、rJava 依赖包、Bioconductor 包。

## Homebrew R 适用场景

- 生物医学数据分析主力环境
- 需要 Java/rJava 配合的包（GEOquery, biomaRt）
- 复杂 Bioconductor 包（Seurat, clusterProfiler）
- 期刊发表级图形输出

## conda R libgfortran 依赖链修复

```bash
conda install -y --force-reinstall -c conda-forge libgcc-ng libgfortran-ng
```

修复后可正常加载基础统计包（meta, survival, ggplot2 等），但复杂编译包仍可能失败。

## macOS ARM64 rJava 编译问题

**症状：** `configure: error: C compiler cannot create executables`

**原因：** Homebrew R 在 macOS ARM64 上 JDK 的路径结构和 Intel Mac 不同，R 在 configure 阶段找不到 JNI headers 位置。

**替代方案：** 使用 Python 的 `GEOparse` 替代 R 的 GEOquery，避免 Java/rJava 依赖。

## 建议配置策略


```
Homebrew R → 主力生物医学分析环境（所有重型包）
conda R → 辅助（Python 环境里的 R 桥接 reticulate）
```
