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




## Promoted Entries (2026-05-07)

- 修复1：`_docking.py` 顶部添加导入：`from autodock._interactions import ..., render_interactions_2d; from autodock._rendering_3d import render_scene` (daily log, 2026-05-07)

- 修复1：`_docking.py` 顶部添加导入：`from autodock._interactions import ..., render_interactions_2d; from autodock._rendering_3d import render_scene` (daily log, 2026-05-07)

- 修复：在 `_core.py` 的 `DockingResult` 中添加三个字段 `png_2d: str | None = None; png_3d: str | None = None; output_dir: str | None = None` (daily log, 2026-05-07)

- 修复：在 `_core.py` 的 `DockingResult` 中添加三个字段 `png_2d: str | None = None; png_3d: str | None = None; output_dir: str | None = None` (daily log, 2026-05-07)

- 修复：重构 `prepare_receptor_with_waters` — 在 meeko 调用**之前**预过滤 skip_linkers={'02J','010','PJE','NFH','NFN'}，保留 HOH/WAT/H2O (daily log, 2026-05-07)


## Promoted Entries (2026-05-07)

- `_autodock.py`: 修复 `_parse_ligplot_hhb`/`_parse_ligplot_nnb`，移除 `use_ghostscript`，修复 LIGPLOT 配体识别 (daily log, 2026-05-06)

- `_autodock.py`: 修复 `_parse_ligplot_hhb`/`_parse_ligplot_nnb`，移除 `use_ghostscript`，修复 LIGPLOT 配体识别 (daily log, 2026-05-06)

- 根因：6LU7 含 02J/010/PJE linker 残基，`allow_bad_res=True` 对 bonded unknown residues（linker）无效 (daily log, 2026-05-07)

- 根因：6LU7 含 02J/010/PJE linker 残基，`allow_bad_res=True` 对 bonded unknown residues（linker）无效 (daily log, 2026-05-07)

- 为 π-π (pistacking) 新增独立分支：用 `item.proteinring.center` 设置 `prot_center`（protein ring centroid），存入 `_prot_center`，后续 nearest-atom fallback 不覆盖 (daily log, 2026-05-05)


## Promoted Entries (2026-05-07)

- 根因：`@dataclass(slots=True)` 的 `DockingResult` 没有 `__dict__`，`dr.png_2d = ...` 报错 (daily log, 2026-05-07)

- 根因：`render_scene` 的第一个参数是 `pdb_path`，而 `dock_single` 用 `receptor_pdb=` (daily log, 2026-05-07)

- 关键发现：`object.__setattr__` 对 `slots=True` dataclass 也无效（与普通 class 不同） (daily log, 2026-05-07)

- **修复**: 改为先调用 `detect_interactions_plip()` 获取相互作用列表，再传递给渲染函数 (daily log, 2026-05-06)

- **原因**: 直接传递 `args.poses`（字符串路径）给 `render_interactions_2d` 的 `interactions` 参数（应为列表） (daily log, 2026-05-06)


## Promoted Entries (2026-05-08)

- **逻辑bug**：`'GLY A 501' in l or 'TYR A 502' in l` 的 OR 本身是对的，但**这整个检查只针对 6LU7 这一个 PDB**。换其他含共结晶配体的 PDB（如 HIV-1 蛋白酶 1BVE 含 JG1），PLIP 会再次把共结晶配体误识别为待分析配体，导致相互作用映射全部错误。 (daily log, 2026-05-07)

- **修复**：改为 `# Set output paths (fields already defined in DockingResult dataclass)` (daily log, 2026-05-07)

- **`ensemble_mode=True`**（默认）：通过 `_generate_receptor_variants()` 对口袋附近残基做 CA 为中心的侧链旋转（8 步 × 45°），生成多个受体构象变体，对每个变体分别对接，最后从全部结果中选最优 pose。这是常见的 **ensemble docking** 策略，比真正的柔性残基更实用。 (daily log, 2026-05-07)

- **autodock 技能** — P0/P1 全部修复，68 项测试通过，git 提交 `c7fd3c6` (daily log, 2026-05-07)

- **慢测试套件：** 6项全部通过（含 `dock_single` SMILES对接、`batch_docking` 2×2矩阵、`screen_ligands` end-to-end） (daily log, 2026-05-07)
## Promoted Entries (2026-05-07)

- **openclaw-plugin-management** (skill, 2026-04-24)
  OpenClaw 飞书插件管理与配置调整。当你想了解 OpenClaw 内置 feishu 插件和新收编的 openclaw-lark 官方插件的关系时；当需要安装、更新、卸载飞书官方插件时；当需要启用流式输出（streaming）或多任务并行（threadSession）功能时；当 openclaw-lark CLI 没有 uninstall 命令不知道如何卸载时——使用此技能。两套飞书插件并存

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