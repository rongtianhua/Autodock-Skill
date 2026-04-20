# memos-dreaming cron 排查与修复记录

## 问题描述

memos-dreaming 的 cron 任务状态显示为 `error`，但实际脚本运行正常，输出"没有新条目需要提升"。

## 根本原因

**Bug: 永远处于 dry run 模式**

脚本末尾的 argparse 逻辑：
```python
dry_run = args.dry_run or not args.apply
```

cron 调用时未传 `--apply` 参数，导致：
- `args.apply = False`
- `dry_run = True`
- 不写入 MEMORY.md

**Bug 2: 投递失败**

原 cron trigger 配置无 `--to` 参数，飞书推送失败。

## 修复方案

创建入口脚本 `memos_dreaming_cron.py`，默认 `apply=True`：

```python
# skills/memos-dreaming/scripts/memos_dreaming_cron.py
if __name__ == "__main__":
    sys.argv.extend(["--apply"])
    sys.exit(main())
```

cron trigger 加上 `--to [飞书频道]` 参数。

## 验证方法

```bash
# 手动触发测试
python skills/memos-dreaming/scripts/memos_dreaming_cron.py

# 检查 cron 状态
openclaw cron list
```

- Status: ok ✅
- Delivery: delivered ✅

## 反思

- 看到 error 状态后注意力在"状态报告"，未去读脚本 argparse 代码
- 过于信任已有配置，觉得"之前能跑就没问题"
- 两次看到"没有新条目"时接受了表面结果，没有追问"为什么一直没有"
