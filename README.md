# aiQAsystem —— 企业知识库智能问答系统

> 智231 小组 · AI大模型智能体应用开发综合实训（终期项目）

## 项目简介

面向企业文档（PDF / Word / Excel / TXT）的智能问答系统：文档上传 → 知识库构建 → 语义检索 + 重排序 → 带引用来源的答案生成。

- 核心功能：多格式文档上传、语义检索 + Rerank、带引用来源的答案生成
- 技术栈：FastAPI + LangChain + Chroma + Embedding + Rerank + DeepSeek + Streamlit

## 团队成员

| 角色 | 姓名 | 职责 |
| :--- | :--- | :--- |
| PM 项目经理（组长） | 胡亦杨 | 计划、进度、会议、风险、答辩统筹 |
| RA 需求分析师 | 待填 | 需求文档、功能规格、验收标准 |
| AD 架构设计师 + 知识库/向量库工程师 | 待填 | 架构设计、知识库与向量库搭建 |
| DEV 智能体开发工程师 | 待填 | RAG流程、API开发、单元测试 |
| PE Prompt工程师 | 待填 | Prompt优化、效果评估、质量报告 |
| UI 智能体交互工程师 | 待填 | 界面开发、联调、演示 |

## 快速开始

```bash
git clone https://gitee.com/the-tiger-king/aiQAsystem.git
cd aiQAsystem
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # 填入自己的 API Key
```

## 仓库规范

- 协作规范：[CONTRIBUTING.md](CONTRIBUTING.md)
- 任务分工：[docs/项目任务分工.md](docs/项目任务分工.md)
- 分支：`master`（稳定版） / `dev`（集成） / `feature/<模块>`（个人开发）
- 提交：`feat|fix|docs|refactor|test|chore(模块): 说明`
- 保密：`.env` 禁止提交，API Key 只放本地

## 周计划

- 当前周任务看板：[docs/第2周任务清单.md](docs/第2周任务清单.md)

- 第1周 ✅：基础搭建 + 需求定稿（FastAPI + DeepSeek 打通，tag week1）
- 第2周 🔄：RAG 核心链路（上传 → 检索 → 带引用回答）
- 第3周：检索优化（Rerank）+ 体验打磨
- 第4周：整合测试 + 答辩
