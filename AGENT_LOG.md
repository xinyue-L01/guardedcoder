# AGENT_LOG

按课程与 PLAN G1 要求记录智能体角色、技能、人工干预与教训。每完成一个实现 task 追加一条；本文件在 G1 创建。

---

## 2026-08-13 · 过程基线（G1）

- **Task：** G1 仓库流程基线（无业务代码）
- **主开发智能体：** Cursor Agent + Superpowers（brainstorming → writing-plans；G1 文档与 git 基线）
- **辅助设计审查：** Codex。阅读课程要求、审查 Cursor 每轮输出并提供回复草案；学生确认、操作并最终签字。该 Codex 会话已见完整设计史，**不能**充当冷启动陌生智能体。
- **G0 冷启动智能体：** OpenCode（glm-5.2）。类型不同于 Cursor；全新 session；不导入历史或 memory；仅提供 `SPEC.md` + `PLAN.md`。
- **G0 结果：** 仓库外 disposable workspace 试做 T01 + T02；约 **43 分钟**；T01 红→绿、T02 红→绿；终态 **4 passed**。因网络/镜像冲突暂停后，有限授权为仅访问 PyPI 安装/解析开发依赖；禁止真实 LLM、API Key、其它服务、原项目访问与 push。
- **G0 文档修订：** 据此修订 SPEC/PLAN（setuptools、`python -m pytest`、piptools 固定命令、`StrEnum` 与完整枚举、`models/__init__.py`）。**未复制**任何 disposable 源码、测试、锁文件或 pyproject 到正式仓库。
- **人工干预：** 产品负责人**已最终签署 G0 通过**。授权执行 G1。本步不执行 T01。
- **教训：** 冷启动必须能真正跑红绿；PLAN 对 pyproject/Windows 测试命令/锁文件 index 写含糊时，陌生 agent 会停或猜。G0 允许的网络必须白名单到 PyPI，避免误连 LLM。

后续每条实现日志须含：红灯/绿灯证据、subagent、人工修改、两阶段评审。
