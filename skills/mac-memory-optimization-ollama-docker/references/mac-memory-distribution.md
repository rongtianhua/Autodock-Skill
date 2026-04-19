# macOS 内存分布参考

## 健康内存状态指标（16GB Mac mini）

| 状态 | 空闲内存 | 说明 |
|------|---------|------|
| 紧张 | < 500MB | 急需清理 |
| 正常 | 2–4GB | 适合日常使用 |
| 良好 | > 4GB | 有足够余量 |

## 典型内存分布（清理后）


| 进程/组件 | 占用 | 备注 |
|-----------|------|------|
| 系统框架（wired）| 2.5 GB | macOS 基础占用，正常 |
| Ollama | 1.5 GB | 模型服务 |
| Colima VM | 1.2 GB | Docker 运行时 |
| openclaw-gateway | 900 MB | AI 网关 |
| Chrome（10标签）| 2–2.5 GB | 每个标签约 200–300MB |
| 压缩内存（compressor）| 1–2 GB | 取决于空闲量 |
| 其他杂项 | ~500MB | v2rayN、WindowServer 等 |

## Chrome 对内存的影响

关闭 Chrome 后的典型效果：
- 空闲内存：2.4GB → 4.5GB（约翻倍）
- 压缩内存：2.3GB → 1.1GB（减少约 50%）

**经验**：Mac mini 16GB + 多 Chrome 标签 = 容易内存紧张。

## 查看命令

```bash
# 按内存排序的前 20 个进程
ps aux --sort=-%mem | head -20

# 系统内存总览（需安装）
# 可以用 htop 或 Activity Monitor
```
