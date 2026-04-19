# Mac mini 内存约束场景注意事项

## 环境信息

| 指标 | 数值 |
|------|------|
| 总内存 | 16GB |
| 已用 | ~15GB |
| 空闲 | ~400MB |

## 受影响场景

内存密集型应用（如 methylation-clock demo 模式）在内存不足时触发 OOM。

## 症状

- pyaging 0.1.30 正常安装
- 实际使用无碍
- Demo 模式因 OOM 失败

## 建议

### 运行 methylation-clock 前

```bash
# 关闭不必要的后台服务
pkill -f some_service_name

# 或使用 zsh 命令临时关闭 Spotlight
sudo mdutil -a -i off
```

### 监控内存

```bash
# 查看内存使用情况
top -l 1 | grep "PhysMem"

# 或使用 htop
htop
```

## 替代方案

- 直接运行 Python 脚本而非 demo 模式
- 使用内存更小的数据集进行测试
- 在其他机器上运行内存密集型任务