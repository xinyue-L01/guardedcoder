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

- **Git：** 默认分支 `main`；基线 commit `53075f05fc5097655d7f5b2f1113b2fbc884da4c`。未设置 origin（无真实 GitHub 仓库则禁止虚假 URL）。
- **自查：** 正式仓无 pyproject、src 业务代码、测试、锁文件；未从 disposable 复制实现。
- **G1 审查修正：** Codex 审查发现 `.cursor/` 当时未跟踪，因此原先“工作区干净”的声明不准确。已将 `.cursor/` 加入 `.gitignore`，不提交本地 Cursor 设置。

---

## 2026-08-14 · T01 工程骨架 + pip-tools

- **Task：** T01（WT-A / `feat/a-foundation` / `.worktrees/wt-a-foundation`）。未执行 T02。未复制 G0 disposable 代码。
- **Implementer：** Cursor generalPurpose subagent `2974ac89-4f8c-4c5a-9c09-89b3fc73bc15`
- **Spec reviewer：** Cursor generalPurpose subagent `2c93cff4-c00c-4798-8881-7776f0c743fb` → Spec compliant，Approved；无 Critical/Important。Minor：`[project.optional-dependencies].dev` 为 brief 未要求的多余项（保留）。
- **Quality reviewer：** Cursor generalPurpose subagent `a6ebe889-2291-4bb8-ad0e-84bff8b709bb` → Task quality Approved。Important：Windows 上 compile 的 hashed lock 含 `pywin32-ctypes`、无 Linux keyring 后端 marker。Controller 裁决：PLAN 锁文件命令固定且不含 `--universal`，不改命令。Minor：版本双处手写、dev extra 与 `.in` 重复。
- **Controller：** Cursor Agent + Superpowers（using-git-worktrees、subagent-driven-development、TDD）。
- **Human edits：** none（实现源码未经人工改写）。
- **红灯：** 仅有 `tests/test_pkg_import.py` 时 `.venv\Scripts\python.exe -m pytest tests/test_pkg_import.py -v` → collection ERROR，`ModuleNotFoundError: No module named 'guardedcoder'`（预期）。
- **绿灯：** 同一命令 `tests/test_pkg_import.py::test_package_version PASSED`；`python -m pytest` → **1 passed**。
- **回归：** commit 前再次 `python -m pytest tests/test_pkg_import.py -v` → **1 passed**。
- **锁文件：** `python -m piptools compile --generate-hashes --allow-unsafe --index-url https://pypi.org/simple` 分别编译 `requirements.in` / `requirements-dev.in`；lock 仅含 `https://pypi.org/simple`，含 sha256 hash，非 `pip freeze`。
- **实现 commit：** `0421cc9463e304c1dadfd293aaab253108f8a4d5`（`feat: add setuptools project skeleton`）。
- **推送：** `feat/a-foundation` → `origin/feat/a-foundation`。本机无 `gh`，**未创建** Draft PR-A（不虚构）。GitHub 手工开 PR：https://github.com/xinyue-L01/guardedcoder/pull/new/feat/a-foundation

---

## 2026-08-14 · T01 Codex 独立验收与仓库卫生

- **Codex 独立验收：** 测试 **1 passed**；editable install 成功。
- **发现：** `.superpowers/` 未写入 `.gitignore`，main 与 WT-A 均出现未跟踪 Superpowers 状态目录。
- **修复：** `main` 提交 `af43e54dca4ee8d21cb124c153c769d77e701ae8`（`chore: ignore local Superpowers state`）加入 `.superpowers/`；WT-A 以 merge（非 rebase）并入 `origin/main`，未改写 T01 实现 commit `0421cc9463e304c1dadfd293aaab253108f8a4d5`。
- **文档：** PLAN G1 备注改为真实 origin `https://github.com/xinyue-L01/guardedcoder`；下一实现 task 改为 T02（以状态表为准）。
- **Human edits：** 产品负责人根据 Codex 独立审查下达本卫生修正；未执行 T02。

---

## 2026-08-14 · T02 RunState / ArtifactState

- **Task：** T02（WT-A / `feat/a-foundation`）。未执行 T03。
- **Implementer：** Cursor generalPurpose subagent `312defdd-7a53-423a-9d3d-64feda9860fe`
- **Spec reviewer：** `4b1742bd-1b1a-47a4-bd04-05ebcb43ce76` → Spec compliant，Approved；无 Critical/Important。
- **Quality reviewer：** `f0a477bf-29b2-49f8-8a6f-99413dccfbb3` → Approved；无问题。
- **Human edits：** none
- **红灯：** 仅有 `tests/test_enums.py` 时 `.\.venv\Scripts\python.exe -m pytest tests/test_enums.py -v` → `ModuleNotFoundError: No module named 'guardedcoder.models'`（预期）。
- **绿灯：** 同命令 2 passed；全量 `python -m pytest` **3 passed**（controller 复跑确认）。
- **实现 commit：** `ba3e36cb2ba812c57bc3f9340b1171b2495eb3ba`

---

## 2026-08-14 · T03 动作 schema

- **Task：** T03（WT-A / `feat/a-foundation`）。未执行 T04。
- **Implementer：** `286a8228-02b3-4f49-b29d-2e5d348ea596`
- **Fixer：** `1a202982-cc89-4360-ac2b-ac7ba2623fb0`（质量 Important：`strict=True`；oversized 改为合法超长 JSON）
- **Spec reviewer：** `d65c8642-c353-4da6-945e-fa339f2022ed` → Spec compliant，Approved。
- **Quality reviewer：** 初审 `8c18f56e-42d6-47f0-a81b-bc93040d1066` Needs fixes（Important×2）；复审 `1eb30006-a980-4bdd-9ab1-d0f1ccd05e00` Approved。Minor：未 frozen、RecursionError、错误信息粗。
- **Human edits：** none
- **红灯：** 仅测试时 `pytest tests/test_actions.py -v` → `ModuleNotFoundError: No module named 'guardedcoder.errors'`。
- **绿灯：** 初版 4 passed / 全量 7 passed；修复后 `test_actions` 5 passed，全量 **8 passed**。
- **实现 commit：** `f33e675658b20450502c287e7310d224049a933f`；收紧 `92a671f0c9afed19fe714a708fcf24e3af6d27fb`

---

## 2026-08-14 · T04 Envelope / CommandProfile

- **Task：** T04（WT-A / `feat/a-foundation`）。未执行 T05。
- **Implementer：** `b76982f7-378e-4a3e-a564-b03fc099a59d`
- **Fixer：** `c761c9e9-49d1-4730-95c1-519a9720683d`（argv_template 存为不可变 tuple，构造仍接受 list）
- **Spec reviewer：** `7cf2002f-f125-4b66-ac0c-af8e3fe640fb` → Spec compliant，Approved。
- **Quality reviewer：** 初审 `dcbc183c-7e2a-4a40-a78a-b153e8b7644b` Needs fixes（Important：可变 list）；复审 `45c11dca-5831-4ea6-94e6-165e166981ab` Approved。Minor：hash 默认空串覆盖、测试未钉死 SHA256 字节。
- **Human edits：** none
- **红灯：** 仅测试时 `ModuleNotFoundError: No module named 'guardedcoder.models.envelope'`。
- **绿灯：** 初版 2 passed / 全量 10 passed；修复后 envelope 3 passed，全量 **11 passed**。
- **实现 commit：** `0118410aae2f38bfdb361a2040762fb6cbdd7781`；冻结 `95d11d261233ee05336019567480f6e2a8044d68`

---

## 2026-08-14 · T05 指纹绑定上下文

- **Task：** T05（WT-A / `feat/a-foundation`）。未执行 T06。未合并 PR-A。
- **Implementer：** `6c646d02-34c9-4b23-8b8d-f79ff13edf77`
- **Spec reviewer：** `1c0aea1b-de05-4bed-80e0-7133df23f300` → Spec compliant，Approved。
- **Quality reviewer：** `a0321e35-3dc7-49b8-ad32-597c2f11474f` → Approved；无 Critical/Important/Minor。
- **Human edits：** none
- **红灯：** 仅测试时 `ModuleNotFoundError: No module named 'guardedcoder.fingerprint'`。
- **绿灯：** `test_fingerprint.py` 2 passed；全量 **13 passed**。
- **实现 commit：** `bf52b007645c0ae165066efd5482b1aa0e36a5a6`

---

## 2026-08-14 · Codex branch-level follow-up（envelope_hash Minors）

- **性质：** Codex 独立验收后的 **branch-level follow-up**。不重做 T02–T05；**不改 T04 已完成状态**（T04 实现 commit 仍为 `95d11d261233ee05336019567480f6e2a8044d68`）。argv_template 不可变 tuple 已完成，未重做。
- **Implementer：** `3c483a27-d8f2-4785-b47a-e9bf3cb7ef23`
- **Quality reviewer：** `07244bad-a483-442b-b19e-87c79b99fce8` → Approved；Critical/Important = 0。
- **Human edits：** none
- **红灯：** `test_explicit_envelope_hash_raises_validation_error` → `Failed: DID NOT RAISE ValidationError`（当时静默覆盖）。
- **绿灯：** `tests/test_envelope.py` 5 passed；全量 **15 passed**。钉死 digest `06694b4f73d148902ba8baa28be3110ed98a3b32a8ef22761b707a9829ba6f45`。
- **Follow-up commit：** `692abb57e5c6282f9fddca7dffe3c48b3832500a`






