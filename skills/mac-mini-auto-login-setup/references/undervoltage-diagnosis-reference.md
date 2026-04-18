# Mac mini 欠压重启诊断参考

## 诊断日志位置

```
/System/Library/Logs/DiagnosticReports/
ResetCounter-<日期>.diag
```

## 关键日志字段

```
Boot failure count: 1
Boot faults: uv, vdd_boost_uvlo rst sgpio
```

| 字段 | 含义 |
|------|------|
| `uv` | 供电电压跌落（Under-Voltage） |
| `vdd_boost_uvlo` | 电源芯片欠压锁定保护触发 |
| `rst` | 系统复位 |
| `Boot failure count` | 失败启动尝试次数 |

## 可能原因排查

1. **电源适配器供电不足** — 输出不稳定
2. **电源线接触不良** — DC电源线/插头松动
3. **负载过大** — USB设备/显示器等超过供电能力
4. **电源砖老化** — 长期使用后电容衰减

## 排查建议

- 检查电源线是否插紧，换插座试试
- 检查电源适配器是否发热严重
- 是否有 USB-C Hub/拓展坞连接过多设备
- 若问题重复出现，考虑更换电源适配器

## 远程诊断命令

```bash
# 查看最近 1 小时的系统日志
log show --predicate 'process == "kernel"' --last 1h | grep -i "reset\|panic\|under-voltage"

# 检查电源状态（部分型号支持）
system_profiler SPPowerDataType
```

## 注意事项

- 欠压保护是正常的安全机制，不表示硬件故障
- 瞬时断电（如跳闸）会导致此现象
- 如果频繁发生（每周多次），建议更换电源适配器
