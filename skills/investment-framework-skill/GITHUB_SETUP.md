# GitHub 仓库创建指南

## 创建新仓库

### 步骤 1：访问 GitHub
```
https://github.com/new
```

### 步骤 2：填写仓库信息

| 字段 | 填写内容 |
|------|---------|
| Repository name | investment-framework-skill |
| Description | 基于 13 本投资经典的 AI 辅助投资决策系统 |
| Visibility | Public（公开） |
| Initialize with README | ❌ 不勾选 |

### 步骤 3：创建仓库
点击 "Create repository" 按钮

---

## 推送本地代码

### 方式 A：使用 HTTPS（推荐）

```bash
# 进入项目目录
cd /tmp/investment-framework-skill

# 添加远程仓库（替换 YOUR_USERNAME 为你的 GitHub 用户名）
git remote add origin https://github.com/YOUR_USERNAME/investment-framework-skill.git

# 推送代码
git push -u origin main
```

### 方式 B：使用 SSH

```bash
# 生成 SSH Key（如果没有）
ssh-keygen -t ed25519 -C "your_email@example.com"

# 添加 SSH Key 到 GitHub
# 访问：https://github.com/settings/ssh/new
# 复制 ~/.ssh/id_ed25519.pub 内容

# 添加远程仓库
git remote add origin git@github.com:YOUR_USERNAME/investment-framework-skill.git

# 推送代码
git push -u origin main
```

---

## 验证推送

推送成功后，访问：
```
https://github.com/YOUR_USERNAME/investment-framework-skill
```

应该能看到：
- README.md
- MEETING_NOTES.md
- DATA_API_GUIDE.md

---

## 后续更新

```bash
# 修改文件后
git add .
git commit -m "更新说明"
git push origin main
```

---

## 邀请协作者（可选）

1. 访问仓库 Settings
2. 点击 "Collaborators"
3. 输入协作者 GitHub 用户名
4. 发送邀请

---

*创建时间：2026-03-13*
