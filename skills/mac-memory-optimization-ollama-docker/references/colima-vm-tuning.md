# Colima VM 内存调优

## 正常内存占用范围

| 场景 | 占用 |
|------|------|
| Colima 默认 VM | ~1.2–1.3 GB |
| Lima hostagent（单个）| ~70–100 MB |
| Colima daemon + shell | ~120 MB |

这是正常现象，不是因为有问题。Colima 使用 Apple Virtualization.framework 分配了 2GB 内存配额给 Linux VM。

## 查看 Colima 配置

```bash
# 查看当前配置
cat ~/.colima/default/colima.yaml
```

典型配置：
```yaml
cpus: 2
memory: 2048  # MB，可调整
disk: 60
```

## 调整 Colima 内存

编辑 `~/.colima/default/colima.yaml`，修改 `memory` 值后重启：

```bash
colima stop
colima start
```

## Colima vs Docker Desktop 内存对比

| 方案 | VM 内存占用 |
|------|------------|
| Colima | ~200MB（轻量）|
| Docker Desktop | ~2GB+（含 GUI 管理服务）|

**结论**：已使用 Colima 时，Docker Desktop 可以完全退出以节省约 2GB。
