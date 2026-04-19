# ClawBio Methylation-Clock 使用备忘

## 运行命令

```bash
/Users/memou/.openclaw-agents/clawbio/venv/bin/python \
  /Users/memou/.openclaw-agents/clawbio/skills/epigenetic-age/run.py \
  --input /Users/memou/test_bio_sample.csv
```

## 成功标志

生成以下文件：
- `tables/predictions.csv` — 每个样本的具体预测值
- `figures/clock_distributions.png` — 时钟分布图
- `reproducibility/commands.sh` — 可复现命令
- `reproducibility/environment.yml` — Conda 环境配置

## 包含的表观遗传年龄时钟

| 时钟 | 说明 |
|------|------|
| Horvath 2013 | 经典表观遗传时钟 |
| AltumAge | 深度学习增强时钟 |
| PCGrimAge | GrimAge 改进版 |
| GrimAge2 | 最新 GrimAge 版本 |
| DunedinPACE | 衰老速度测量（非年龄）|

## 典型输出

| 时钟 | 平均预测年龄 | 标准差 |
|------|------------|--------|
| Horvath 2013 | ~27岁 | ±1.5 |
| AltumAge | ~21岁 | ±4.4 |
| PCGrimAge | ~85岁 | ±2.3 |
| GrimAge2 | ~61岁 | ±0.9 |
| DunedinPACE | ~1.29 | ±0.04 |

## 内存需求

methylation-clock 运行需要一定空闲内存（建议 > 2GB）。如果内存紧张，可先关闭 Chrome 或 Ollama 腾出空间。
