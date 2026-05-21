# 此目录已冻结（FROZEN）

**冻结日期**：2026-01

## 状态
本目录是 Alpine.js + 单文件 `app.js` 的老前端，已进入**冻结状态**。

## 政策
- ❌ 不再接受新功能
- ❌ 不再接受 UX 改进
- ⚠️ 严重 bug 才修（数据丢失、安全问题、阻断启动）
- ✅ 主开发都在 `frontend-next/`

## 访问入口
- 默认根路径 `/` → 新前端（`frontend-next/dist`）
- 老前端挂在 `/legacy`，仅供回滚 / 对照参考

## 删除计划
当 `frontend-next/` 功能追平且作者用它完成一本书的完整流程后（参考 `docs/project_review.md` Phase A），本目录将被删除。

## 如果你需要在这里改东西
先问：`frontend-next/` 能不能做到？如果能，去那边改。
