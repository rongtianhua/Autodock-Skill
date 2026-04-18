# MemOS 迁移功能说明

## 用途
将 OpenClaw 原生 memory 系统（MEMORY.md、daily notes、session-state 等）中积累的历史记忆，迁移到 MemOS 的 SQLite 数据库，避免切换插件后记忆丢失。

## 迁移流程
1. 扫描 OpenClaw 原生记忆文件（memory/*.md、daily notes 等）
2. 智能去重（向量相似度 + LLM 判断重复内容）
3. 断点续传（可暂停、刷新后继续）
4. 可选生成任务摘要和技能进化

## 当前状态
你之前用 OpenClaw 内置记忆积累的内容，因为 memory-core 一直是禁用状态，所以实际上并没有太多记录。如果之前有手动写过 MEMORY.md 或其他记忆文件，可以尝试迁移。

## 操作入口
MemOS 管理面板 → 记忆页面 → 导入/迁移功能
