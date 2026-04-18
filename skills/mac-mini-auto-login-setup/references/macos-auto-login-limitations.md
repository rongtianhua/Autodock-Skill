# macOS 自动登录已知限制

## 突然断电后的行为

即使已配置自动登录，以下情况会导致登录延迟或卡住：

| 情况 | 表现 | 处理方式 |
|------|------|----------|
| **fsck 磁盘检查** | 启动时强制检查文件系统，可能持续 2-3 分钟 | 耐心等待 |
| **系统状态不稳定** | 断电前处于睡眠状态，恢复时可能崩溃 | 长按电源键 5 秒强制重启 |
| **文件系统错误** | 日志显示异常 | 按 Cmd+R 进入恢复模式检查 |

## 自动登录本身配置正确

```bash
# 验证配置
sudo defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser
# 应返回：allenrong
```

自动登录功能已正确启用。遇到卡在登录界面时，问题通常是上述临时状态，而非配置失效。

## 快速诊断命令

```bash
# 查看启动日志（诊断重启原因）
log show --predicate 'process == "kernel"' --last 1h | grep -i "reset\|panic\|under-voltage"

# 查看是否有 fsck 正在运行
ps aux | grep fsck

# 检查文件系统状态
diskutil verifyVolume /
```
