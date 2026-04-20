# ISP 代理 + CDN 连通性排查指南

## 网络链路

```
Mac (V2RayN TUN) → VPS (Mack-a) → ISP SOCKS5 代理 → CDN 边缘节点
  [跳1]              [跳2]            [跳3]              [跳4]
```

**关键澄清**：第4跳是 ISP 代理独立发起连接，走 ISP 代理自己的路由，不是 VPS 直连。

## 排查步骤

### 1. 确认出口 IP

```bash
curl --proxy socks5://127.0.0.1:10808 https://ipinfo.io/json
```

重点字段：
- `org` → AS 号（数据中心 vs ISP）
- `hostname` → reverse DNS
- `is_proxy` → 是否被标记为代理

### 2. 测试特定 CDN 域名

```bash
# 走代理测试
curl -sI --proxy socks5://127.0.0.1:10808 --connect-timeout 8 https://cdn-updates.orbstack.dev/
curl -sI --proxy socks5://127.0.0.1:10808 --connect-timeout 8 https://brew.sh/

# 直连测试（绕过代理）
curl -sI --connect-timeout 8 https://cdn-updates.orbstack.dev/
```

## 代理服务商对比

| | Proxy Cheap | Proxy Seller |
|---|---|---|
| 出口 IP | AS10753 Level 3（数据中心骨干）| AS701 Verizon Business（ISP 骨干）|
| 定位 | 低端，用数据中心 IP 冒充 ISP | 中端偏上 |
| CDN 路由 | 不稳定（被 Cloudflare/Fastly 封锁）| 部分 CDN 仍不通 |

## 常见问题

**Q: ISP IP 还是被 CDN 封锁？**

可能原因：
1. IP 之前被滥用，IP 声誉数据库（Spamhaus/PBL）标记为风险
2. 代理服务商"ISP IP"实际是机房广播（IP 伪装）
3. CDN 查 BGP 前缀，即使 IP 类型是住宅，AS 号暴露机房身份

**Q: 绕行规则何时需要？**

当特定 CDN 域名持续超时，但其他网站正常时，考虑：
- 加绕行规则让目标域名直连（绕过代理）
- 或更换代理出口节点

## 绕行规则配置

域名：`orbstack.dev`、`brew.sh`（视情况添加其他 CDN 域名）
