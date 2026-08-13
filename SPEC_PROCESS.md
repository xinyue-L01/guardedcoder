# SPEC_PROCESS.md

记录 GuardedCoder 从 brainstorming 走到 SPEC 签字、PLAN 生成、G0 冷启动试做与文档回写的过程。第 7 节已记录 OpenCode 试做；**待产品负责人最终签署 G0**。未复制 disposable 代码。

### 工具角色

- **主开发智能体：Cursor Agent + Superpowers。** 负责 brainstorming、写入 `SPEC.md` / `PLAN.md` / `SPEC_PROCESS.md`。
- **辅助设计审查：Codex。** 阅读要求、审查 Cursor 每轮输出并提供回复草案；**学生负责确认、操作和最终签字。**
- **当前 Codex 已看到完整设计历史，因此绝不能充当之后的陌生冷启动智能体。** G0 实际使用的是 **OpenCode（glm-5.2）** 全新 session。
- 多智能体使用应继续在 `AGENT_LOG.md` 如实记录（G1 起该文件存在于正式仓）。

- 日期：2026-08-13
- 设计状态：五块设计已签字；`SPEC.md` / `PLAN.md` 已按 G0 发现修订；**G0 已签署，进入 G1**（G0 Commit 仍为 `—`）。



---

## 1. 工作方式

按 brainstorming 清单：先读要求，再澄清与分块签字，然后写 SPEC；SPEC 审查通过后由 writing-plans 生成 PLAN。G0 已签署。实现代码须等 **G1 基线完成之后**。


提问阶段共 7 轮（每轮 2–3 个方案 + 推荐）。设计呈现 5 块，多数块先有补丁再整体签字，而不是一次通过。

---

## 2. 至少三轮关键迭代

### 迭代 1：第一用户与自治边界（提问第 1–2 轮）

**AI 问了什么：** 产品是给谁用的？默认哪些动作自动跑、哪些必须 HITL？

**AI 建议：**

- 用户选「本地开发者的受限自主编码助手」，而不是课程演示器或 CI 补丁机器人。
- 自治用「每次任务一份可确认的策略信封」，默认信封内容接近内置风险分级，永不允许规则不可放宽。

**人工采纳：** 方案 A 用户 + 方案 B 信封。把产品收窄为：单仓库、边界明确的小任务、不 push / 不部署 / 不多 agent；审计是工程属性不是产品定位。信封列出工作区真实路径、读写范围、命令配置、预算、网络/删除策略。

**为何算关键：** 后面所有机制（worktree、指纹、verify、记忆）都挂在「任务级不可变信封」上，而不是隐式 deny-list。

---

### 迭代 2：隔离 worktree，并人工推翻「脏文件可 HITL」（提问第 3 轮）

**AI 问了什么：** 改动发生在用户当前工作树、隔离 worktree，还是目录副本？

**AI 建议：** 推荐隔离 Git worktree。当时仍沿用上一轮「任务开始时已有未提交改动则 HITL 后可改」的信封字段。

**人工采纳 worktree，同时否决脏文件 HITL。** 修订为：

- 只支持已初始化且至少一 commit 的本地 Git 仓库；
- 原工作树必须干净才能启动；
- 不干净则明确拒绝，不自动 commit / stash / 删除；
- agent 只在 harness 管理的任务 worktree 操作；
- 成功后默认只输出 patch，显式 `apply` 才回原树；
- 暂停恢复必须跨进程，状态原子写入。

**原因：** 隔离后 agent 看不到原树未提交内容；若仍允许 HITL 改「脏文件」，恢复时会把人类改动和 agent 改动混在一起。这是一次**人工设计修订**，应保留：AI 推荐了正确的隔离方向，但脏树策略必须由人改掉。

**为何算关键：** 这是范围收缩，直接决定启动前置条件、apply 预检和失败清理模型。

---

### 迭代 3：网络 / OS 沙箱承诺修正，以及旧稿事故（设计第 1 块）

**AI 最初写了什么：** 范围里出现「永远禁止外部网络访问」一类过宽承诺；US-4 容易被读成「任意测试进程也不能联网」。LLM 能力被写成「LLM 仅五工具」，漏掉任务描述、记忆和 observation 仍会进入模型。US-3 曾把未知命令、装依赖与可审批动作混在一起。US-10 把评分者写成产品用户。

**人工否决过宽承诺，要求准确表述：**

- 不向 LLM 提供通用网络工具，也不能临时构造 curl / push / publish；
- push / 发布 / 部署是产品级硬拒绝；
- Provider HTTP 是内部控制通道；
- 已确认 profile 在宿主机执行，没有 OS 沙箱，内部代码理论上仍可能联网；
- 前提是仓库与 profile 可信，**不宣称**子进程网络隔离。

并区分：worktree 内越写入范围可 HITL；逃出 worktree 必须硬拒绝。未知 profile 不是普通动作审批。装依赖首版不能经审批放行。US-10 移出用户故事，改为课程 NFR。

**操作事故（不算人工设计决策）：** 第 1 块曾因误操作重新生成旧稿，把已被否决的内容（例如脏文件 HITL、过宽网络承诺、把评分者当用户）带回来。产品负责人明确：这次重新生成**不是**新的设计决策，只是事故后的纠正。后续 SPEC 以纠正补丁后的签字稿为准。

**为何算关键：** 若按旧稿实现，治理会被写成做不到的 OS 沙箱，评分和威胁模型都会假。

---

### 迭代 4：指纹、崩溃窗口、状态拆分（设计第 2 块）

**AI 最初写了什么：** 指纹主要哈希规范化动作；状态机把 `applied` / `discarded` 接在 `succeeded` 后面；「策略只收紧」没分开「一次评估」和「新版信封」；执行中崩溃几乎没写；「LLM 看不见原工作树」说得过满。

**人工要求补齐 main contribution 语义（全部采纳）：**

1. 指纹绑定 `schema_version, task_id, envelope_hash, base_commit, worktree_identity, normalized_action`；审批还绑定 pending action 与 `state_revision`，只能消费一次，禁止跨任务/信封/状态重放。
2. 副作用前必须进入 `executing_action`。`apply_patch` 用 pre/postimage 恢复；`run_command` 停在执行窗口只能 `error`，不得自动重跑。
3. `run_state` 与 `artifact_state` 分离；apply 只允许 `succeeded` + `patch_ready`；discard 不覆盖执行结果。
4. 一次评估只收紧；用户确认的新版信封可在硬规则内扩大普通范围。
5. 文件工具围栏不等于 OS 进程沙箱。

**为何算关键：** 没有这些，跨进程恢复和 HITL 只是「把 y/n 存盘」，算不上治理主贡献。

---

### 迭代 5：模块接口收紧（设计第 3–4 块，摘要）

第 3 块八模块切分被接受，但 AI 初稿有几处会被实现钻空子，人工全部改掉：

| AI 初稿问题 | 人工修订 |
|---|---|
| M3 输出「有界 patch」 | 完整 patch 禁止静默截断；有界的只是 summary，须标哈希与位置 |
| M5 接收「曾被 M4 放行的 Action」 | 执行前再校验并颁发一次性 `ExecutionPermit`；M5 拒裸 Action |
| 未知 profile 与硬禁止写成同一种拒绝 | `COMMAND_NOT_ALLOWED` vs `HARD_FORBIDDEN_COMMAND` |
| M5 有时自己标 ERROR | M5 只返回 `CommandResult`；Verdict 只由 M7 产生 |
| M7 在 finish 时直接跑 verify | M6 编排，每个 verify 再走 M4+permit+M5；无 verify → 明确进入 `unverified` |
| 审批可能只靠 task ID 或 y/n | `approve <task-id> <fingerprint>` |
| apply-back 无执行窗口 | `applying` + pre/postimage；混合态禁止自动重试 |

第 4 块再补：M3 生命周期操作不用 LLM permit；单步必须「M8 先建窗口再让 M5 执行」；SQLite 外键、单活动 pending/permit、`state_revision`、事务失败无副作用。

---

## 3. AI 建议采纳 / 否决一览

**采纳（AI 提出，人工确认）：**

- 第一用户定为本地开发者，不做 Cursor 替代品。
- 策略信封作为任务契约，而不是纯隐式分级。
- 隔离 worktree，成功后显式 apply。
- 最小工具集 + 唯一写入 `apply_patch`，不向 LLM 开放 Git。
- 类型化 sensor + `finish(success)` 门闩；无测试不能冒充成功。
- 结构化记忆 + 确定性检索，不做向量库。
- Python 3.12 + pytest + keyring + wheel Release；系统 Git 为外部依赖。
- 治理作为 main contribution。
- 八模块切分（M1–M8）。
- 审查阶段补齐声明式 TOML 配置（第六维），不放宽硬边界。
- 冻结 argparse、Pydantic v2、defusedxml、`guardedcoder`、GitHub + Actions，并保留 `.gitlab-ci.yml` `unit-test`。

**否决或大幅修正（人工）：**

- 脏工作树可经 HITL 修改（否决，改为启动前置条件）。
- LLM 可写入长期记忆（否决，只允许建议 + 用户 `memory add`）。
- 把所有越界都做成可审批（否决，硬边界不可放行）。
- 过宽的「子进程不能联网 / OS 沙箱」承诺（否决）。
- 仅哈希动作文本的指纹（不够，必须绑执行上下文）。
- `applied` 作为 `succeeded` 的下一执行状态（否决，拆产物状态）。
- 裸 Action 交给执行器（否决，必须有一次性 permit）。
- 为演示拒绝而新增网络工具（否决，未知 action 走 schema 拒绝）。
- US-10 作为产品用户故事（否决，改为课程 NFR）。
- 静默截断完整 patch（否决）。
- `.env` 作为凭据来源（否决自动加载）。
- 把校验和说成能防托管平台整体失陷（否决该表述）。
- 用配置关闭或放宽硬拒绝（否决）。
- 把 API Key 写入 TOML 或 `.env`（否决）。
- 让已看过完整设计史的 Codex 充当冷启动陌生智能体（否决）。

**第 5 块签字前人工补强（采纳进 SPEC）：** Provider 的 HTTPS / loopback HTTP / 禁止重定向转发 Authorization / 按当前 provider 取 key；源码离机隐私告知；依赖锁定与 CI 干净构建。

---

### 迭代 6：SPEC 审查补配置维并冻结技术选择（文档审查，非实现）

**起因：** 课程六维要求「配置」必须是声明式机制；初版 SPEC 把配置写进信封字段，但缺少独立的用户配置文件、schema 与 CLI。技术栈仍留「argparse 或轻量 CLI」「Pydantic 或 dataclass」「托管平台计划前确定」「CLI 可改名」。

**人工要求（全部写入 SPEC，不改硬边界）：**

- OS 用户目录 versioned TOML + Pydantic v2 严格 schema；Key 永不进 TOML；硬拒绝由代码定义。
- 配置 + CLI 合成待确认信封，展示最终有效值。
- `config init|validate|show`；非法配置不建 worktree、不调 LLM。
- 冻结：`argparse`、Pydantic v2、`defusedxml`、CLI 名 `guardedcoder`、GitHub 仓库与 Release + Actions，同时保留 `.gitlab-ci.yml` 的 `unit-test`。
- 工具角色写明 Cursor 主开发、Codex 辅助审查；**本 Codex 会话不能当冷启动陌生智能体。**

**为何算关键：** 补齐第六维，同时去掉会让 PLAN/冷启动猜测技术栈的未决项。

---

### 迭代 7：PLAN 审查修订（writing-plans 之后，未执行 G0）

**AI 初稿问题与人工要求（已写入修订后的 `PLAN.md`）：**

1. G0 改为仓库外 disposable 试做 T01+T02，允许写代码但不得进正式仓。
2. 增加 G1：Git、安全 gitignore、AGENT_LOG、基线提交、GitHub、worktree 从已合并 main 创建。
3. AGENT_LOG 改到 G1；每 task 追加；T42 只审计。
4. permit：M8 创建并消费+开窗，M5 只验证。
5. T29 用 PatchArtifactPort stub，真实导出 T32，集成 T43；T30 门控 FAIL Verdict；JUnit 用本次运行唯一路径与 `{junit_out}`。
6. 补 discard 归属、CLI 全家、memory CLI、100/90 清理、AuditEvent、e2e。
7. pip-tools `--generate-hashes`，不用 pip freeze。
8. 秘密扫描先于 CI；假 key 拼接；Actions 分 push/PR 与 tag Release。
9. 增加 G2 人工交付（含学生自写 REFLECTION、submission.jsonc 并列规则）。
10. 压缩 Step 1–8 改为固定八步勾选。

**本轮不执行 G0。**

---

## 4. 对 brainstorming 技能的即时观察

做得好的地方：强制一问一答和分块签字，把「脏树」「沙箱承诺」「指纹绑定」这些会在实现里爆炸的假设逼到明处；主贡献没有停在 deny-list 口号。

让人不满的地方：第 1 块曾在误操作后吐出旧稿，把已否决内容当新稿，需要人立刻对照否决项，而不能假设「重新生成 = 已对齐」。另外 AI 几次把治理说满（看不见原工作树、所有副作用都经 permit 到 M3、有界 patch 当交付物），人必须把边界写回「文件工具围栏 ≠ 沙箱、生命周期操作 ≠ LLM permit」。

这些观察供 `REFLECTION.md` 日后展开；本文只记录事实，不代写反思报告。

---

## 5. 旧稿重新生成事故（再次声明）

设计第 1 块呈现之后、签字之前，发生过一次误操作，导致重新生成的文本恢复了已被否决的内容。产品负责人指示：**不要把该次重新生成记录为新的人工设计决策。** 有效决策以随后的修订补丁和第 1 块正式签字为准。`SPEC.md` 已按补丁后文本整合。

---

## 6. 已签字设计块清单

| 块 | 内容 | 状态 |
|---|---|---|
| 1 | 问题陈述、用户、范围、US-1–US-9 | 补丁后整体签字 |
| 2 | 领域与机制、治理主贡献 | 指纹/窗口/状态补丁后整体签字 |
| 3 | 八模块功能规约 | 接口补丁后整体签字 |
| 4 | 架构、数据流、数据模型、依赖 | 副作用入口/顺序/SQLite 补丁后整体签字 |
| 5 | NFR、威胁模型、分发、验收、风险 | endpoint/隐私/供应链补丁后整体签字 |
| 审查补丁 | 声明式配置、技术冻结、GitHub、工具角色 | SPEC 已签字 |
| PLAN | writing-plans 生成；G0 已签署；G1 基线已提交 | G0 passed（Commit —）；G1 done `53075f05fc5097655d7f5b2f1113b2fbc884da4c`；无 origin |

---

## 7. 冷启动验证（已试做，产品负责人已签署）

**未虚构。** 以下为 OpenCode 试做的如实记录。正式仓库**未复制**任何 disposable 代码。

**签署：** 产品负责人已最终签署 G0 通过。**G0 已签署，进入 G1。**

| 项 | 事实 |
|---|---|
| Agent | **OpenCode（glm-5.2）**，类型不同于主开发 Cursor |
| Session | 全新；不导入历史对话或 memory |
| 材料 | 仅 `SPEC.md` + `PLAN.md` |
| 位置 | 正式 `codingAgentHarness` **之外**的 disposable workspace（绝对路径不写入正式仓，以免被当作可复制实现源） |
| 耗时 | 约 **43 分钟** |
| T01 | 红 → 绿 |
| T02 | 红 → 绿 |
| 终态 | **4 passed** |
| 代码去向 | **未**合并、提交或复制进正式仓库 |

**网络/PyPI：** 试做中因网络/镜像冲突暂停。有限授权后，G0 **仅**允许访问 PyPI（`https://pypi.org/simple`）安装与解析开发依赖。禁止真实 LLM、API Key、其它服务、访问原项目目录、push。该规则已回写 `PLAN.md` G0。

**暴露的 SPEC/PLAN 缺陷（陌生 agent 受阻点）：**

1. `pyproject.toml` 未写明 build-system / src discovery / pytest 路径，T01 猜测空间过大。
2. 缺少 `src/guardedcoder/models/__init__.py`，包导入边界不清。
3. 权威测试写成 `make test`，Windows 无 make 时无法按字面验收。
4. 锁文件未冻结 index URL 与 `--allow-unsafe`；本机私有/系统镜像可能被写进 lock。
5. T02 示例只列三个枚举值，未强制 SPEC §6.5 全集与 `StrEnum`。

**修订前后关键 diff（文档，非代码）：**

| 主题 | 修订前 | 修订后 |
|---|---|---|
| 构建 | 未冻结后端 | setuptools；pyproject 最小字段写死 |
| 测试命令 | `make test` 像硬验收 | 权威 `python -m pytest`；Makefile 可选 |
| 锁文件 | 笼统 pip-compile | 固定 `python -m piptools compile --generate-hashes --allow-unsafe --index-url https://pypi.org/simple …`；禁止私有镜像 URL 进提交 lock |
| 枚举 | 测三个值即可 | `StrEnum` + §6.5 全集合断言；补 `models/__init__.py` |
| G0 网络 | 未写 | 仅 PyPI；禁 LLM/Key/其它服务/原项目/push |
| G0 状态 | pending / 未执行 | **passed** 且 **已签署**；Commit **—**；进入 G1 |

PLAN Status：G0 = passed，Commit = `—`。**G0 已签署，进入 G1。** 正式仓未复制 disposable 代码。

---

## 8. 下一步（尚未执行）

1. G1 已完成（基线 `53075f05fc5097655d7f5b2f1113b2fbc884da4c`，无 origin）。
2. 下一实现 task：**T01**（正式仓按修订规则重做，不粘贴 disposable 代码）。**本 G1 回合未执行 T01。**
3. 按 worktree 从最新已合并 main 创建；每 task 更新 AGENT_LOG 与 PLAN 状态栏。
4. 全部实现与 T43 后走 T42 文档审计，再 **G2** 人工交付。
