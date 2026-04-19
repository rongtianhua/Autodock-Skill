# Cloudflare CDN 与数据中心 IP 阻断

## 问题描述

在国内访问某些托管在 Cloudflare CDN 上的域名时，出现 SSL 握手超时，即使翻墙后仍无法访问。

## 根本原因

Cloudflare 对所有来自**数据中心/云服务商 IP** 的连接采用标准安全策略：

- 在 CDN 层面直接拒绝 SSL 握手
- 与具体翻墙协议无关
- 常见受影响 IP 段：AWS、GCP、Azure、Level 3 (AS10753) 等

## 溯源方法

```bash
# 查看翻墙服务器出口 IP
curl ifconfig.me

# 或通过 ipinfo.io 查询 IP 详情
curl ipinfo.io/<IP>
```

## 受影响场景

| 服务 | CDN 域名 | 症状 |
|------|----------|------|
| OrbStack | `cdn-updates.orbstack.dev` | SSL_ERROR_SYSCALL |
| Docker Hub | `registry-1.docker.io` | 连接超时 |
| GitHub CDN | `githubusercontent.com` | 可能超时 |

## 解决方案

1. **换节点**：使用标注"住宅 IP"或"原生 IP"的翻墙节点
2. **自建代理**：使用有住宅 IP 的 VPS
3. **绕过域名**：将特定 CDN 域名加入直连规则（不推荐，效果有限）

## 判断依据

- 直连超时 → 可能是 DNS 污染
- 翻墙后仍超时 → 检查出口 IP 是否为数据中心 IP
- `SSL_ERROR_SYSCALL` → Cloudflare 主动拒绝

## 注意事项

- Colima 走 Homebrew 自托管的 GitHub bottle，不经过 Cloudflare CDN
- 对于 ClawBio 这类工具，Colima 功能完全等价
- 住宅 IP 节点通常比数据中心 IP 节点更稳定