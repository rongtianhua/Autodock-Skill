# MEMORY.md — Long-Term Memory

## About the User
- Name: Allen Rong (戎天华)
- Timezone: Asia/Shanghai
- Occupation: Spine surgeon, Beijing

## Projects
- **ClawBio 全面部署** (2026-04-19): `~/.openclaw/clawbio/`，50个生物信息学技能；Python依赖已装；R 4.5.3 + Bioconductor 11个包；Docker via OrbStack；路由skill: `clawbio-wrapper/SKILL.md`
- Tushare stock skill (Python 3.14 installed)
- MemOS memory plugin: fully installed 2026-04-10 (bge-m3 embedding + MiniMax-M2-7 summarizer)
- a-stock-trader-pro skill: v2.2/v2.3 released with major data fixes
- **FUSION TWAS框架** (2026-04-20): `~/bioinformatics/fusion_twas/`，依赖散落（conda PLINK + Homebrew R + GCTA via Rosetta 2）
- **Homebrew R 全量生信包** (2026-04-20): WGCNA/GWAS/TWAS/ML/表观遗传学 R 包全部就绪（35个包，仅echostat因无R4.5缺席）
- **单细胞虚拟敲除/扰动工具** (2026-04-20): scgen(Python), scGPT, DrugReflector, Geneformer, scvi-tools, scPred, CellOracle Docker
- **pubmed-pdf-downloader skill** (新建): PMC PDF下载 → DOI → CrossRef API → Springer直链，成功率高于直接抓取；所有PDF存 workspace/Documents/
- **飞书文档读写**：权限已开通（docx:document + drive:drive），可直接写入飞书文档

## Decisions Log
- Switched to local Ollama bge-m3 embeddings for memory (2026-04-08)
- Session-state stored at workspace root
- Git-Notes cold storage enabled for permanent knowledge (2026-04-08)
- MemOS installed as primary memory system (replaces Dreaming/memory-core)
- **Docker运行时: OrbStack替代Colima** (2026-04-19): 用户解决V2RayN网络问题后安装OrbStack 2.0.5；Colima已删除；Docker完全切换到OrbStack
- **conda环境结构** (2026-04-20): `scvi`(Python3.11/scvi-tools+scGPT+DrugReflector), `scgen`(Python3.9/scvi1.1.6+scgen), `geneformer`(Python3.10/geneformer完整包), `pwas`(Python3.9), `mdanalysis`(Python3.11), `autodock`(Python3.11)
- **memos记忆写入规则** (2026-04-18): 用户说“记住XX”→写memory/YYYY-MM-DD.md；MEMORY.md只接受系统蒸馏结果+用户明确指令
## Lessons Learned
- **2026-04-20: R包安装大小写敏感** — SeqArray(大写S)、plink2R(大写R)等包名必须严格准确，不能猜；生物医学包名必须严谨
- **2026-04-20: preprocessCore/impute需BiocManager** — CRAN无ARM64版本，需`BiocManager::install()`而非`install.packages()`
- **2026-04-20: echostat无R 4.5** — CRAN尚未更新，接受替代方案不死磕；TWAS已有TwoSampleMR+coloc+gsmr覆盖
- **2026-04-20: GCTA官方无ARM64** — 需从GitHub下载x86_64二进制，Rosetta 2转译运行无性能损失
- **2026-04-20: scvi._compat修复scgen** — scgen 2.1.0依赖旧版scvi API（LossRecorder），在scvi 1.1.6中不存在；修复：创建compat shim（LossRecorder→LossOutput桥接）+ 在scvi.module.base.__init__中补充导出
- **2026-04-20: torchtext源码编译解决scGPT** — conda二进制torchtext与torch 2.11.0 ABI不兼容；`pip install torchtext --no-binary :all:` 从源码编译0.6.0版本解决
- **2026-04-20: DrugReflector pip安装bug** — PyPI wheel错误地将`drug_reflector.py`映射为`drugreflector`；`pip install -e ~/bioinformatics/drugreflector/ --no-deps` 从源码安装解决
- **2026-04-20: Geneformer循环导入修复** — jkobject/geneformer克隆有错误导入（从in_silico_perturber导入了不存在的函数）；正确代码在HF ctheodoris/Geneformer；修复：替换emb_extractor.py为HF版本 + 打补丁in_silico_perturber.py（延迟导入get_embs）；ctheodoris/Geneformer是正确源码
- **2026-04-19: Docker Desktop VM进程PPID=1** — 无法普通kill，需sudo kill -9；OrbStack和Colima底层均为Lima+Apple Virtualization.framework
- **2026-04-14: 报告模板标准化** — 确立标准格式：实时行情快照 + 五维特征萃取(含杜邦+YoY) + 综合决策指示(具体价位) + 风险清单(5项) + 仓位速查表
- **2026-04-14: Sina bid/ask索引** — 验证方法：直接print raw parts array，用已知好价格确认索引位置
- **2026-04-14: 两处dataclass同步bug** — 加新字段时，RawMarketData和MarketSentiment两处都要改，容易遗漏
- **2026-04-14: baostock季度回溯** — 4月中旬2025年报未发布，必须回溯到Q3/Q2
- **2026-04-12: cron 定时任务必须指定 target** — `--target <user_open_id>`，isolated模式下不指定会报错
- **2026-04-08: Never restart gateway without checking active tasks** — 今天的飞书会话损坏教训
- **Check ≠ Fix** — 用户说"检查"时只检查，修复前必须询问
- **Assess impact before destructive operations** — 配置守护脚本进行变更影响评估

## 安全实践（2026-04-18）
- Keychain 条目管理密码（条目名："Mac sudo"，用户：allenrong）
- sudo NOPASSWD 已配置（/etc/sudoers.d/allenrong）
- 绝不在聊天中明文传输密码；用 Keychain 管理

## Mac mini 稳定在线（2026-04-18）
- 自动登录：已配置（`/Library/Preferences/com.apple.loginwindow autoLoginUser`）
- sudo免密：已配置（/etc/sudoers.d/allenrong）
- Keychain："Mac sudo"管理 sudo 密码
- 重启排查：`last reboot` / `pmset -g log`
- Limitation：突然断电后需等 fsck 完成；电源恢复设置可能导致循环重启

## 技能安装记录
详见 `memory/YYYY-MM-DD.md` 每日日志

## Preferences
- Use local models where possible
- Context: workspace /Users/allenrong/.openclaw/workspace

---
*Curated memory — distill insights from daily logs here*