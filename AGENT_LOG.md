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

---

## 2026-08-14 · T06 AppConfig（WT-B）

- **Implementer：** `797bf1c9-38f7-49c6-a6ae-bf87b8b6fa46`
- **Fixer：** `3360dc32-55e1-4d48-a547-ef64a76629c8`（假 key 改为拼接）
- **Spec reviewer：** `28a85fb0-2ff8-43a0-ac1a-33fec59cb00a` → Approved（Minor 假 key 已修）
- **Quality reviewer：** `d62ec361-4e99-43d4-974a-2f14bbbb505a` → Approved
- **Human edits：** none
- **红灯：** `ModuleNotFoundError: guardedcoder.models.config`
- **绿灯：** `test_appconfig` 3 passed；全量 **18 passed**
- **实现 commit：** `16ee5ab711a8e4797395f6bedf949d572ab4d1b9`；假 key `a09cbdb30c1e8be9ccde85528c04a2f406be29c9`

---

## 2026-08-14 · T07 TOML fail closed（WT-B）

- **Implementer：** `763cabac-c673-4216-9a62-2f20103b6b67`
- **Fixer：** `c899559d-521d-45d4-a952-fb5ff164700a`（UnicodeDecodeError→ConfigError）
- **Spec reviewer：** `38d4dd69-cfa4-4e18-baed-f3ddaa0c61af` → Approved
- **Quality reviewer：** 初审 `9fac507d-6064-4db1-84e8-303707a295f6` Needs fixes；复审 `43497b27-00f8-4ea0-aa39-9aceea224120` Approved
- **Human edits：** none
- **红灯：** `ModuleNotFoundError: No module named 'guardedcoder.config'`
- **绿灯：** 修复后 `test_config_load` 12 passed；全量 **30 passed**
- **实现 commit：** `856630970d6a93f634fefa5bdd95958dcc06aeb7`；decode `2b882a53bc33b517a514e923c0f8d3f94ff9a155`

---

## 2026-08-14 · T08 合成信封（WT-B）

- **Task：** T08（WT-B / `feat/b-config`）。未执行 T09。
- **Implementer：** `4ffb7183-eeab-46f5-9a1c-62efd61a13d8`
- **Fixer：** `7bf90a91-fe69-43de-853b-b49f90d289a7`（未知 CLI 键与非法覆盖 → ConfigError）
- **Spec reviewer：** `52947829-054a-4d6a-ba62-b40b78570bad` → Approved
- **Quality reviewer：** 初审 `9bea2213-d773-4499-b565-56a4e9bd6739` Needs fixes（Important×2）；复审 `557b4026-241c-4211-aa8a-4987a9ae1f85` Approved。Minor：config_digest 测试复制算法。
- **Human edits：** none
- **红灯：** 初版 `ModuleNotFoundError: guardedcoder.config.synthesize`；修复前未知键 `DID NOT RAISE ConfigError`，非法 `max_steps` 漏出 `ValidationError`。
- **绿灯：** 修复后 `test_synthesize` 7 passed；全量 **37 passed**。
- **实现 commit：** `012bd06d35c975682536e9239ae98993c7a611b4`；覆盖校验 `d7658c0e66cefeffddda3ce44af088437729dfda`

---

## 2026-08-14 · T09 配置不能放宽硬规则（WT-B）

- **Task：** T09（WT-B / `feat/b-config`）。未执行 T12。未合并 PR-B。
- **Implementer：** `9c5b16dc-f902-4bc4-af5f-76b5446bdd85`
- **Spec reviewer：** `87f9be7e-8aac-4f8b-8a05-d9a6e50344da` → Approved。Minor：`pip` 精确 token，不覆盖 `pip3`/`pip.exe`。
- **Quality reviewer：** `325ab50d-71c0-4d29-b58f-f3f708bae69f` → Approved；Critical/Important/Minor = 0。
- **Human edits：** none
- **红灯：** `ModuleNotFoundError: No module named 'guardedcoder.governance'`
- **绿灯：** `test_config_hard_rules` 7 passed；全量 **44 passed**。
- **实现 commit：** `840129835f79aa89e0ed95e15b7df337f02a99ba`

---

## 2026-08-14 · T10 MockLLM（WT-C）

- **Implementer：** `5019ad99-f365-46ff-a182-10f79ff1842a`
- **Spec reviewer：** `1e45a676-fc6e-4b1a-86b6-47199fe8d2b6` → Approved
- **Quality reviewer：** `62e14274-592f-4195-9131-dbe5a6b749fc` → Approved
- **Human edits：** none
- **红灯：** `SecretLeakError` / LLM 模块导入失败
- **绿灯：** 全量 **19 passed**
- **实现 commit：** `1fbba589d6e4a919756cd8e7765c3bb14cdddf0e`

---

## 2026-08-14 · T11 OpenAICompatibleLLM（WT-C）

- **Implementer：** `c0d78c08-0b5c-4963-b278-6f9cc6d5e06a`
- **Fixer：** `579b90dd-c4df-46eb-abd1-9c359bb1f996`（HTTP scheme 大小写）
- **Spec reviewer：** 初审 `684f3055-4e75-446e-9d23-851c12c2feb6` Needs fixes；复审 `8ff3abaa-1b06-48fe-8cb6-95bf5169bf37` Spec ✅
- **Quality reviewer：** `22f9d011-89a5-441a-8b92-cc02ad1fa6c1` → Approved
- **Human edits：** none
- **红灯：** `RemoteKeyHttpError` / openai_compat 模块导入失败
- **绿灯：** 修复后 `test_openai_compat` 8 passed；全量 **27 passed**
- **实现 commit：** `8afe6c20d14b84f3c1211bb63e03e7d19cd8fcb5`；scheme `44edd47821598ebd4e898c0e1a9ef91c7965e488`

---

## 2026-08-14 · T12 路径围栏（WT-D）

- **Task：** T12（WT-D / `feat/d-governance`）。未执行 T13。
- **Implementer：** `fdf2e2a3-21c5-4e53-bc2f-c8290c628579`
- **Fixer：** `09990800-332c-446b-bb4b-cda40247a55a`（`.ENV` 大小写、祖先 `.env.*`、`is_relative_to`）
- **Spec reviewer：** `6fd26715-bbc2-4f3f-9d9e-60c2c78dea24` → Spec ✅
- **Quality reviewer：** 初审 `e3a08dc1-215a-47ed-8b24-e2d0e2de8d70` Needs fixes；复审 `e8008e47-6a15-430a-bcb4-477510b28469` Approved。C/I=0。
- **Human edits：** none
- **红灯：** `ModuleNotFoundError: No module named 'guardedcoder.governance.fence'`；修复前 `.ENV`→ok、祖先 `.env.*` 误敏、`..foo` 误逃逸。
- **绿灯：** 修复后 `test_fence` 8 passed / 1 skipped；全量 **64 passed, 1 skipped**。
- **实现 commit：** `a262669dac93b01846aba41e0083415ebc60572f`；收紧 `6ce301aac696ba0d1cdcef9f6320682958c520d9`

---

## 2026-08-14 · T13 硬规则与 profile 分码（WT-D）

- **Task：** T13（WT-D / `feat/d-governance`）。未执行 T14。
- **Implementer：** `63b18d80-0640-4cac-a9aa-c88db25d11b1`
- **Fixer：** `c8c81f29-7dd4-4809-ae4e-1b432f3a224f`（argv token 不用宿主 Path）
- **Spec reviewer：** `5b8f41e4-994a-4e0e-800d-4adf3fed863a` → Spec ✅。Minor：su/runas/pkexec 无专测。
- **Quality reviewer：** 初审 `8a2582c1-ad30-4b5f-a4fc-201cb0386043` Needs fixes；复审 `e343d2df-eec4-4421-9234-b664d8788d4d` Approved。C/I=0。
- **Human edits：** none
- **红灯：** `ImportError: cannot import name 'ProfileKind'`
- **绿灯：** 修复后全量 **88 passed, 1 skipped**。
- **实现 commit：** `81529a15a5880fdcd952abcc42479ba213515019`；规范化 `dcb5be736912c184fd41aa9af2c18036b31526ad`

---

## 2026-08-14 · T14 风险分类（WT-D）

- **Task：** T14（WT-D / `feat/d-governance`）。未执行 T15。
- **Implementer：** `ac8faf42-7072-4216-92e7-48d24be29529`
- **Spec reviewer：** `3757b5be-a5a0-4233-88cb-40fff6bda72b` → Spec ✅
- **Quality reviewer：** `eb0dca3a-a156-4a3e-a8dd-7be62f4e6f02` → Approved。C/I/M=0。
- **Human edits：** none
- **红灯：** `No module named 'guardedcoder.governance.classify'`
- **绿灯：** `test_classify` 8 passed；全量 **96 passed, 1 skipped**。
- **实现 commit：** `2423edd5ba9a930966057afe82ec57aa6ada6eb1`

---

## 2026-08-14 · T15 治理求交评估（WT-D）

- **Task：** T15（WT-D / `feat/d-governance`）。未执行 T16。未合并 PR-D。
- **Implementer：** `acdc0eb3-2ae3-4917-8f10-e39f0d10ff37`
- **Spec reviewer：** `e7886828-a75c-482f-bae4-92579d4dc7ff` → Spec ✅
- **Quality reviewer：** `53ea4328-3656-4a3e-8822-3be93cc94f18` → Approved。C/I/M=0。
- **Human edits：** none
- **红灯：** `ModuleNotFoundError: No module named 'guardedcoder.governance.evaluate'`
- **绿灯：** `test_evaluate` 9 passed；全量 **105 passed, 1 skipped**。
- **实现 commit：** `78b8beef5c7a9d044a7076d4c60905d3a8895090`

---

## 2026-08-14 · PR-D follow-up（evaluate read_paths）

- **性质：** PR-D 独立验收 Important。不执行 T16；**不改 T15 已完成状态**（T15 实现 commit 仍为 `78b8beef5c7a9d044a7076d4c60905d3a8895090`）。
- **Implementer：** `42996148-4bd4-451d-a34a-9164c3ed7d17`
- **Spec reviewer：** `25b9ed06-824d-4d42-9f51-6c50c9fae2c9` → Spec ✅
- **Quality reviewer：** `40d0e45b-96c4-4310-aa3c-615d5f5f9e77` → Approved。C/I=0。Minor：NeedApproval 对 classify_read 不可达；两处测试未正断言 Deny。
- **Human edits：** none
- **红灯：** `test_read_file_under_write_paths_only_is_not_allow` → `assert Allow != Allow`（`src/a.py` 被 write_paths 误放行）。
- **绿灯：** 全量 **111 passed, 1 skipped**。
- **Follow-up commit：** `d10f324e91eb7b7dca70a7ae1f5e63d0f56ea61e`

---

## 2026-08-14 · T16 SQLite、Task、AuditEvent 脱敏（WT-E）

- **Task：** T16（WT-E / `feat/e-persist`）。未执行 T17。未合并 PR-E。
- **Implementer：** Cursor generalPurpose `d1817fc4-3828-48dc-9e5a-0e9bf6896d55`
- **Spec reviewer：** `de6ecf7c-aaac-48ba-ae68-8ba73a9a183a` → C/I=0
- **Quality reviewer：** `372b061d-c105-4fbc-b3b3-43a7f40d3719` → C/I=0
- **Human edits：** none
- **红灯：** collection `ImportError`（缺 persist 模块 / `StaleRevisionError`）
- **绿灯：** `test_db` 7 + `test_audit` 1；全量 **119 passed, 1 skipped**
- **实现 commit：** `3006440dc5989058a3609aeb08aaf101553e134c`

---

## 2026-08-14 · T17 M8 创建并消费 permit（WT-E）

- **Task：** T17（WT-E / `feat/e-persist`）。未执行 T18。未合并 PR-E。
- **Implementer：** `015c6a89-3990-47a8-b567-f0b188f1a629`
- **Spec reviewer：** `0b084675-65e2-44eb-8f13-77fc63971073` → C/I=0
- **Quality reviewer：** `2e249fa2-0541-4c66-b944-eaa2e3797ad1` → C/I=0。Minor：缺 task 误报 StaleRevision；缺 permit 用 LookupError。
- **Human edits：** none
- **红灯：** 缺 `persist.permit` / `PermitConsumedError`
- **绿灯：** `test_permit` 8 passed；全量 **127 passed, 1 skipped**
- **实现 commit：** `3eaed9d70322e1f8930eee7fc303f61915573d72`

---

## 2026-08-14 · T18 apply_patch 窗口恢复（WT-E）

- **Task：** T18（WT-E / `feat/e-persist`）。未执行 T19。未合并 PR-E。
- **Implementer：** `5bdf7d88-ec5b-40f8-b514-682f0475a18a`
- **Spec+quality reviewer：** `73e7ae20-84fe-47ea-8b73-1eeaadc157f4` → C/I=0
- **Human edits：** none
- **红灯：** 缺 `persist.recover`
- **绿灯：** `test_recover_patch` 7；全量 **134 passed, 1 skipped**
- **实现 commit：** `45b03c76b328e55067d0028ccd680aad54b4c130`

---

## 2026-08-14 · T19 run_command 窗口 fail-closed（WT-E）

- **Task：** T19（WT-E / `feat/e-persist`）。未执行 T20。未合并 PR-E。
- **Implementer：** `614d8405-85c8-4cb7-b60c-585ff09eee45`
- **Spec+quality reviewer：** `7e21962e-56b7-48e2-a596-c5d32317bff1` → C/I=0
- **Human edits：** none
- **红灯：** run_command 仍 NotImplementedError / 缺 test_recover_command
- **绿灯：** `test_recover_command` 2；全量 **136 passed, 1 skipped**
- **实现 commit：** `7b8bd894561645935f042eb6ad3aaec4296ee326`

---

## 2026-08-14 · T20 审批一次性（WT-E）

- **Task：** T20（WT-E / `feat/e-persist`）。未执行 T21。未合并 PR-E。
- **Implementer：** `1108d6d4-be4a-490d-845b-ffab79a02d6e`
- **Spec+quality reviewer：** `d4a181de-fe9d-4b42-973e-455d2492c5d2` → C/I=0
- **Human edits：** none
- **红灯：** 缺 `persist.approval` / `ApprovalError`
- **绿灯：** `test_approval` 5；全量 **141 passed, 1 skipped**
- **实现 commit：** `a15bd72e41c6dd681e79553088267f3aafb62f43`

---

## 2026-08-14 · PR-E follow-up（permit 绑定 envelope）

- **性质：** branch-level Important。不执行 T21；**不改 T17 已完成状态**（T17 实现 commit 仍为 `3eaed9d70322e1f8930eee7fc303f61915573d72`）。
- **Implementer：** `87f49a9b-1a12-43c7-a87e-1a0b427e9982`
- **Re-review：** `e6a43fb6-b91a-4fc7-a756-1389962026e8` → C/I=0
- **Human edits：** none
- **红灯：** 改信封后仍能 consume 旧 permit
- **绿灯：** 全量 **143 passed, 1 skipped**
- **Follow-up commit：** `06486647a15c715fbc403937dfa06cd6db0ab054`

---

## 2026-08-14 · PR-E 独立对抗审查（Codex 反例）

- **性质：** 不合并、不执行 T21。systematic-debugging：先写失败测试并记录红灯，再最小修复。
- **红灯（修复前）：** `tests/test_adversarial_*.py` **16 failed, 1 passed, 1 skipped**（见 `.superpowers/sdd/adversarial-red.txt`，未入库）。
  1. stale permit：envelope 不变但 revision 变后仍能 consume（DID NOT RAISE）
  2. 双窗口：executing_action 下仍能 create 第二 permit
  3. 跨进程：create_task/insert_pending/approve 关闭重连后行为丢失
  4. 双连接 approve：成功数 0（无 commit）；revision 变更因无持久化误报 StaleRevision
  5. 恢复 `../` 逃逸：run_state 被标成 running
  6. 全文入库：hash 标记恢复被当成 error
  7. pending_action_id / verifying：TypeError 或 run_state 被改成 executing_action
- **修复 commits：**
  - `97ee8b7` 事务所有权 + 原子审批
  - `97223ab` stale permit / 单窗口 / pending 绑定 / verifying
  - `a09f0a8` SHA-256 镜像 + 围栏
  - `38a38a2` HITL 指纹与 worktree_identity 恢复
  - `92c5717` 已消费 pending 不得跨 revision 发 permit；recover 单事务
  - `357d9a1` preimage 重试认领 revision；流式哈希
- **Spec reviewer：** `41fc13cf` 初审 C3/I1；复审 `59098adb` → **C/I=0**
- **并发/恢复 quality reviewer（独立，未与 spec 合并）：** `8b1b7a83` → `8db0d042` → `6c36180f` → `56969f88`。终态 **C=0**。剩余 I=2（新 revision 再次 recover 认领；pre/post 路径集合不必相同）由 controller 按签字语义驳回：同一次崩溃恢复必须能在认领后继续；创建/删除文件要求路径集合不同。
- **Human edits：** none
- **绿灯：** 全量 **164 passed, 2 skipped**




