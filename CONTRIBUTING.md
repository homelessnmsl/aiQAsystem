# 团队协作规范（组员必读）

## 1. 分支策略

| 分支 | 用途 | 规则 |
| :--- | :--- | :--- |
| `master` | 稳定版本，可演示/交付 | 只允许从 `dev` 合并，禁止直接 push，由 PM 合并 |
| `dev` | 集成开发分支 | 功能完成后通过 Pull Request 合入，须至少 1 人评审 |
| `feature/<模块>` | 个人开发分支 | 从 `dev` 拉出，命名示例：`feature/ingestion`、`feature/api-ask`、`feature/web-ui` |

每日结束前必须 push 到自己的 feature 分支（远端备份），严禁只在本地保存。

## 2. 提交规范

提交信息格式：`<type>(<scope>): <说明>`

| type | 含义 |
| :--- | :--- |
| feat | 新功能 |
| fix | 修复缺陷 |
| docs | 文档变更 |
| refactor | 重构 |
| test | 测试相关 |
| chore | 构建/依赖/杂项 |

示例：`feat(api): 新增 /api/ask 带引用来源的问答接口`

## 3. 协作流程

1. 每个任务先建 Issue（用 Issue 模板），认领后把状态改为"进行中"，并注明自己的角色与分支。
2. 本地开发：`git checkout dev && git pull` → 新建 feature 分支 → 开发 → push。
3. 完成后发起 Pull Request（feature 分支 → dev），在描述里填"关联 Issue #编号"和自测结果。
4. 至少 1 名其他成员评审通过后合并；有冲突先在 dev 上解决再提。
5. PM 每周五从 dev 合并到 master，作为周版本。

## 4. 环境与保密

- 统一 Python 3.12+，依赖全部写入 `requirements.txt`。
- `.env` 存 API Key，**绝不提交**；仅提交 `.env.example` 占位模板。
- 文档统一放 `docs/`，测试数据放 `tests/`，大文件（>5MB）不传仓库，用链接/说明代替。

## 5. Issue 与周会

- 任务、缺陷、风险一律走 Issue，不用聊天记录代替。
- 每周两次同步会（周二、周五），周五出周报，PM 汇总到 `docs/周报/`。
