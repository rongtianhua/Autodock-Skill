# investment-framework-skill 改进计划

**基于 SKILL-STANDARD-v2.md 新标准**

**执行日期：** 2026-03-19

---

## 📊 技能清单（33 个 SKILL.md）

### 核心技能（5 个）- 高优先级
- [ ] value-analyzer
- [ ] moat-evaluator
- [ ] intrinsic-value-calculator
- [ ] decision-checklist
- [ ] asset-allocator

### 高级技能（5 个）- 中优先级
- [ ] industry-analyst
- [ ] cycle-locator
- [ ] future-forecaster
- [ ] portfolio-designer
- [ ] stock-picker

### 全球配置（2 个）- 中优先级
- [ ] global-allocator
- [ ] simple-investor

### 认知工具（2 个）- 中优先级
- [ ] bias-detector
- [ ] second-level-thinker

### 中国大师（11 个）- 中优先级
- [ ] china-masters/SKILL.md
- [ ] china-masters/qiu-guolu/SKILL.md
- [ ] china-masters/qiu-guolu/valuation-analyzer/SKILL.md
- [ ] china-masters/qiu-guolu/quality-analyzer/SKILL.md
- [ ] china-masters/duan-yongping/SKILL.md
- [ ] china-masters/duan-yongping/culture-analyzer/SKILL.md
- [ ] china-masters/duan-yongping/longterm-checker/SKILL.md
- [ ] china-masters/li-lu/SKILL.md
- [ ] china-masters/li-lu/civilization-analyzer/SKILL.md
- [ ] china-masters/li-lu/china-opportunity/SKILL.md
- [ ] china-masters/wu-jun/SKILL.md
- [ ] china-masters/wu-jun/ai-trend-analyzer/SKILL.md
- [ ] china-masters/wu-jun/data-driven-investor/SKILL.md

### 主文件（1 个）- 高优先级
- [ ] SKILL.md（主技能）

---

## 🔧 改进清单

### 每个技能需要添加/改进：

1. **Front Matter**（必需）
```yaml
---
name: skill-name
version: 2.0.0
description: ［何时使用］当用户需要 X 时；当用户说 Y 时；当检测到 Z 时
author: 燃冰 + 小蚂蚁
created: 2026-03-13
updated: 2026-03-19
skill_type: 核心 | 通用 | 实验
related_skills: [skill-a, skill-b]
tags: [标签 1, 标签 2]
---
```

2. **Description 字段优化**
   - 从摘要式改为触发说明式

3. **坑点章节**（必需）
   - 至少 3-5 个常见错误

4. **related_skills 字段**
   - 说明技能组合关系

5. **文件夹结构**
```
skill-name/
├── SKILL.md
├── templates/
├── references/
├── examples/
└── calculators/
```

---

## 📅 执行计划

### 阶段 1：核心技能（本周）
1. ✅ value-analyzer
2. ✅ moat-evaluator
3. ✅ intrinsic-value-calculator
4. ✅ decision-checklist
5. ✅ asset-allocator

### 阶段 2：高级技能（下周）
6. ⏳ industry-analyst
7. ⏳ cycle-locator
8. ⏳ future-forecaster
9. ⏳ portfolio-designer
10. ⏳ stock-picker

### 阶段 3：中国大师（下周）
11. ⏳ china-masters 系列（11 个）

### 阶段 4：其他技能（未来）
12. ⏳ global-allocator
13. ⏳ simple-investor
14. ⏳ bias-detector
15. ⏳ second-level-thinker
16. ⏳ SKILL.md（主技能）

---

## ✅ 完成标准

- [ ] 所有 33 个技能有 Front Matter
- [ ] 所有 Description 是触发说明式
- [ ] 所有技能有 related_skills 字段
- [ ] 所有技能有坑点章节（至少 3 个错误）
- [ ] 计算类技能有.py 脚本
- [ ] 所有技能有 templates/文件夹
- [ ] GitHub 已推送

---

*技能是活的文档，不是一次性产物。*
