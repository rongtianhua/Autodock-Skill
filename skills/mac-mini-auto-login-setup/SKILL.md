---

## 一、开机自动登录配置

### 配置目标

机器重启后跳过锁屏界面，直接进入桌面，OpenClaw 自动启动。

### 操作步骤

```bash
# 方法：直接修改 loginwindow plist
sudo defaults write /Library/Preferences/com.apple.loginwindow autoLoginUser -string "allenrong"
```

### 验证命令

```bash
sudo defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser
# 应返回：allenrong
```

### 安全注意事项

开启自动登录后，任何能物理接触机器的人都能直接进入系统。当前 Mac mini 部署在内网环境，风险可控，但需评估物理访问权限。

### 已知限制

突然断电后启动，macOS 可能触发 fsck 磁盘检查，此时自动登录会延迟 2-3 分钟。遇到此情况需耐心等待，或进入恢复模式（Cmd+R）检查文件系统。

---

## 二、sudo 免密码执行配置

### 配置目标

AI 执行系统维护操作时无需人工输入密码确认，实现自动化运维。

### 操作步骤

```bash
# 编辑 sudoers 文件
sudo visudo
```

在编辑器中添加一行：

```
allenrong ALL=(ALL) NOPASSWD: ALL
```

保存退出（:wq）。

### 验证命令

```bash
sudo -n id
# 应直接返回 uid=0(root)，无密码提示
```

---

## 三、Keychain 密码存储配置

### 配置目标

程序化调用 sudo 时不必明文传输密码，将密码安全存储在系统 Keychain 中。

### 首次存储（仅需执行一次）

```bash
security add-generic-password -a allenrong -s "Mac sudo" -w '你的新密码' -U
```

> **注意事项**：
> - 密码用单引号包裹，避免 shell 特殊字符解析
> - 如果终端出现 `dquote>`，说明引号未闭合，按 `Ctrl+C` 取消，重新输入
> - macOS Keychain Access 应用路径：`/System/Library/CoreServices/Applications/Keychain Access.app`，或用 Spotlight（Cmd+Space）搜索 "keychain"

### 读取使用

```bash
# 从 Keychain 读取密码（用于脚本自动化）
security find-generic-password -a allenrong -s "Mac sudo" -w
```

### 安全说明

- Keychain 用登录密码加密解锁，只要 Mac 有锁屏保护，Keychain 就是安全的
- 不要把密码明文写入聊天记录或明文配置文件
- 建议定期更换密码：`sudo passwd allenrong`

---

## 四、三层保障体系总览

| 层级 | 机制 | 作用 |
|------|------|------|
| **自动登录** | loginwindow plist | 重启后跳过锁屏，直接进桌面 |
| **sudo 免密** | sudoers NOPASSWD | AI 执行维护无需人工确认 |
| **Keychain** | 安全存储密码 | 程序化调用 sudo，不明文传输 |

---

## 五、故障自检清单

当 OpenClaw 离线时，按以下顺序排查：

1. **检查网络** — Mac mini 是否联网
2. **检查电源** — 是否断电或电源故障
3. **检查登录状态** — 是否卡在锁屏界面
4. **查看系统日志** — 诊断重启原因
5. **远程协助** — 如需物理操作，引导用户按电源键

### 常用诊断命令

```bash
# 查看启动日志（诊断重启原因）
log show --predicate 'process == "kernel"' --last 1h | grep -i "reset\|panic\|under-voltage"

# 查看 OpenClaw 进程状态
ps aux | grep -i openclaw

# 强制重启（如远程无法恢复）
sudo shutdown -r now
```

---

## 六、安全红线

- **系统密码仅限用户本人使用**，绝不外泄
- **不主动泄露任何凭证信息** — 包括密码、sudoers 配置、Keychain 内容
- 在给予 AI 操作权限的同时，用户信任 AI 会全力保障系统安全
- 建议定期更换密码，并在密码变更后更新 Keychain 存储

---

## 附录：已解决的问题记录

### Mac mini 重启原因

**根因**：电压不足（Under-Voltage）导致重启。

系统日志显示：
- `uv` — 供电电压跌落
- `vdd_boost_uvlo` — 电源芯片的欠压锁定保护触发
- 系统检测到电压异常 → 触发复位 → 第一次启动失败 → 重试 → 第二次成功启动

**确认**：家中跳闸断电导致，Mac mini 硬件本身无问题。

## Companion files

- `references/macos-auto-login-limitations.md` — reference documentation
- `references/keychain-access-reference.md` — reference documentation
- `references/undervoltage-diagnosis-reference.md` — reference documentation