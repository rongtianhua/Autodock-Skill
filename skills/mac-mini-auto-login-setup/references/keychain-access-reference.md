# macOS Keychain Access 位置参考

## 应用位置

```
/System/Library/CoreServices/Applications/Keychain Access.app
```

## 为什么找不到

- 不在 `/Applications` 文件夹
- 不在 `/Applications/Utilities` 文件夹
- 隐藏在 `CoreServices` 系统目录深处

## 打开方式

| 方法 | 操作 |
|------|------|
| **Spotlight（推荐）** | 按 `Cmd+Space`，输入 `keychain`，回车 |
| **终端** | `open /System/Library/CoreServices/Applications/Keychain\ Access.app` |
| **Finder 前往** | `Cmd+Shift+G`，粘贴路径 |

## 常用 Keychain 命令

```bash
# 存储密码（首次）
security add-generic-password -a <用户名> -s "<服务名>" -w '<密码>' -U

# 读取密码
security find-generic-password -a <用户名> -s "<服务名>" -w

# 删除密码
security delete-generic-password -a <用户名> -s "<服务名>"

# 列出所有项
security list-keychains
security dump-keychain -d
```

## 安全说明

- Keychain 用登录密码加密解锁
- 只要 Mac 有锁屏保护，Keychain 即安全
- 密码用单引号包裹，避免 shell 特殊字符解析
