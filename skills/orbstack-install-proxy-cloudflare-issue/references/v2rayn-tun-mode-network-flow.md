# V2RayN TUN 模式网络流量分析

## TUN 模式 vs 系统代理

| 模式 | 流量处理 | 关闭系统代理后 |
|------|----------|----------------|
| 系统代理 | 仅处理配置了代理的应用流量 | 流量直连 |
| TUN 模式 | 完全接管所有出口流量（虚拟网卡） | 仍走代理隧道 |

## TUN 模式特征

```bash
# 检查是否存在 utun 接口
ifconfig | grep utun
```

- 创建虚拟网卡（utunX）
- 完全绕过系统代理设置
- 所有 TCP/UDP 流量都进入隧道
- `curl` 直连测试仍会经过翻墙通道

## 排查步骤

```bash
# 1. 检查系统代理环境变量
env | grep -i proxy
# 结果示例：
# HTTP_PROXY=http://127.0.0.1:10808
# HTTPS_PROXY=http://127.0.0.1:10808
# SOCKS_PROXY=socks5://127.0.0.1:10808

# 2. 检查 utun 接口
ifconfig | grep utun

# 3. 确认是 TUN 模式还是普通代理
# Tailscale 也用 utun 接口，但不会接管所有流量
# 需要检查 sing-box/v2ray 的配置文件
```

## 关键发现

V2RayN 配置为空（DB 存储），但 `sing-box` 可能在 TUN 模式下运行：

- 系统代理已关闭
- 直连 Cloudflare CDN 仍超时
- 说明所有流量仍在代理隧道内

## 解决方案

在 V2RayN 中找到并关闭 "TUN 模式" 或 "增强模式" 开关。

## 验证方法

```bash
# 关闭 TUN 模式后测试直连
curl -v https://cdn-updates.orbstack.dev
# 如果能建立连接，说明 TUN 模式已生效
```