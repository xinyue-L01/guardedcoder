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
- **并发/恢复 quality reviewer（独立，未与 spec 合并）：** `8b1b7a83` → `8db0d042` → `6c36180f` → `56969f88`。终态 **C=0**。剩余 I=2（新 revision 再次 recover 认领；pre/post 路径集合不必相同）当时由 controller 按签字语义驳回。
- **Human edits：** none
- **绿灯：** 全量 **164 passed, 2 skipped**
- **后续推翻：** 上述 controller 驳回不成立。Codex 第二轮反例证明：`preimage={a}`/`postimage={b}` 即使 b 匹配也不得 succeeded；全 pre 后再用新 revision recover 不得再次认领同一窗口。见下条。

---

## 2026-08-14 · PR-E 第二轮对抗（Codex 反例推翻驳回）

- **性质：** 不合并、不执行 T21。此前 quality I=2 驳回被 Codex 反例推翻，不得由 controller 再驳 Important。
- **四反例测试：** `tests/test_adversarial_round2.py`（disjoint keys、新 revision 不得重认领、succeeded 不得复活、stale insert_pending 零行）。
- **修复 commits：**
  - `719edd3` 同路径集 image、RetryableSameAttempt 不 bump revision、insert_pending 同事务校验、`request_approval`
  - `c2a5a9a` 非法 source_run_state / 损坏 JSON → error；旧库 ALTER
  - `145e7a9` HITL `awaiting_approval` 窗口可 recorded_success；归一化撞键拒绝；`update_task` 不得切入 awaiting_approval
- **Spec reviewer：** `7182cbd2` 对 `c2a5a9a`：**C=2 I=2**。C1 HITL 恒 error、C2 撞键 last-wins 已修进 `145e7a9`；I1 两段审批已堵。
- **并发/恢复 reviewer（独立）：** `9345686e` 对 `c2a5a9a`：**C=1 I=3**。C1 与 spec C1 同因，已修。I1 双 `retryable_same_attempt`、I2 无重驱动原语 **未修**。
- **暂停（交人工/Codex）：** I1/I2 与签署语义冲突：全 pre 必须保持 task/window 不变且 recover 不得用 revision 伪装 claim；真正一次性 retry claim/进程锁要在 T22 接 M5 前完成。Controller **不驳回** 这两条 Important，也不在 recover 里做假 claim。未推送。
- **绿灯（暂停时）：** 全量 **180 passed, 2 skipped**（`145e7a9`）。
- **Human edits：** 产品负责人裁决 C1/I1/I2；未改 persist 实现代码。
- **人工裁决：** C1 接受为已修复。I1 不作为 PR-E blocker：`retryable_same_attempt` 是非授权检查结果，多调用者得到相同结果不代表执行权；`recover()` 必须继续保持 task/window 不变且不得调 executor。I2 记录为后续强制集成要求，不标 won't fix，不改 PR-E 代码。PLAN T24（依赖 T18/T19）加入硬门槛：执行恢复补丁前须独立原子排他 retry claim（绑定 task/window/state_revision/attempt）；M5 无有效 claim 必须拒绝；claim 不可重放；验收含双连接/进程仅一个成功、无 claim 无副作用、崩溃后重核 pre/post、旧 claim 不可重放。该要求完成前 T24/T28 不得标 done。本轮只更新 PLAN 与 AGENT_LOG；不执行 T21。
- **绿灯（裁决后）：** 全量 **180 passed, 2 skipped**。
- **推送：** `feat/e-persist`（不合并、不执行 T21）。

---

## 2026-08-14 · T31 脏树拒绝、创建/discard 归属

- **Task：** T31（WT-I / `feat/i-workspace`）。未执行 T32。未合并 PR-I。
- **Implementer：** lane-i-owner
- **Spec reviewer：** 初审 `4c8e507f-25ff-4e8e-8987-bcad5903bb38` → C/I=0；复审 `ee113a4b-f6a1-4e67-af34-3f4646ab297b` → Spec ✅ C/I=0。Minor：`resolve()` 跟随符号链接。
- **Quality reviewer：** 初审 `710f66bd-1f37-4b07-a5c5-fee62fc2a351` Needs fixes（I=3：HEAD 冻结、Windows 设备名/尾点、缺 `discard_owned_worktree` 测试）；复审 `ab524144-2d7d-4e1b-82e8-a357c09b4ca7` → Approved C/I=0。Minor：remove 后残留、清理异常掩盖原因。
- **Human edits：** none
- **红灯：** `.superpowers/sdd/t31-red.txt` collection `ModuleNotFoundError: guardedcoder.workspace`；审查修复红灯 `foo.` DID NOT RAISE、`NUL` 设备路径、HEAD 移动后 discard 因 `HEAD==base_commit` 拒绝。
- **绿灯：** `tests/test_worktree.py` **18 passed**；全量 **198 passed, 2 skipped**。
- **实现 commit：** `bb1426bc7877a853e8c633022c9245042f8b478c`

---

## 2026-08-14 · T32 完整 patch artifact

- **Task：** T32（WT-I / `feat/i-workspace`）。未执行 T33。未合并 PR-I。
- **Implementer：** lane-i-owner
- **Spec reviewer：** `20300a75-fda7-42f9-9310-abc6d4c12607` → Spec ✅ C/I=0。Minor：`"truncated" in text` 也能匹配 `truncated=false`（已改为断言 `truncated=true`）。
- **Quality reviewer：** 初审 `c01093e7-46bb-4ed0-818e-d8c85c546f5d` Needs fixes（I=1：只查 origin porcelain，锁不住 worktree index）；复审 `6a0339ed-cadb-4b0f-9d37-458bb5bc15fe` → Approved C/I=0。
- **Human edits：** none
- **红灯：** `.superpowers/sdd/t32-red.txt` collection `ModuleNotFoundError: guardedcoder.workspace.artifact`
- **绿灯：** `tests/test_patch_artifact.py` **3 passed**；全量 **201 passed, 2 skipped**。
- **实现 commit：** `940470f27584e790a24dec11da57fcc94f5e4238`

---

## 2026-08-14 · T33 apply-back 窗口

- **Task：** T33（WT-I / `feat/i-workspace`）。未合并 PR-I。
- **Implementer：** lane-i-owner
- **Spec reviewer：** 初审 `2f3cae27-453c-4796-aebe-ed53b1e158c6` Needs fixes（I=1：recover 未校验 `task.repo_path`）；复审 `d119acb1-1d49-4f10-ac85-20c5235b5400` → Spec ✅ C/I=0。
- **Quality reviewer：** 初审 `31e83f6d-e6e0-4776-b82b-099625c8b1bb` I=2（旧库 permit_id NOT NULL；空 postimage 虚真）；`3c3b3bec-9821-428a-bb8d-17bfaacfa7c0` I=1（重建拷贝 NULL opened_revision）；复审 `4c10bce7-9c69-49c5-8f13-91050274431e` → Approved C/I=0。
- **Human edits：** none
- **红灯：** `.superpowers/sdd/t33-red.txt` collection `ModuleNotFoundError: guardedcoder.workspace.apply_back`
- **绿灯：** `tests/test_apply_back.py` **14 passed**；全量 **215 passed, 2 skipped**。
- **实现 commit：** `83d97079dea01938072d68e4cb76d283a059dcd1`

---

## 2026-08-14 · PR-I branch follow-up（diff 路径解析）

- **性质：** branch-level Critical/Important。不改 T33 已完成状态（T33 实现 commit 仍为 `83d97079dea01938072d68e4cb76d283a059dcd1`）。
- **Implementer：** lane-i-owner
- **Spec reviewer：** 初审 `ac2082b9-7879-4a40-91ba-6fae9b9729b8` I=1；`51ffef5e-ca5d-4530-85b9-a885929ad10d` I=1（C-octal）；复审 `2bd67a16-98a6-4b2b-bb5e-1f9dac9a968a` → Spec ✅ C/I=0。
- **Quality reviewer：** 初审 `dcc2f948-e8d6-4d7b-aa6b-5086ea93040b` C=1；`62f8adba-4d6c-493f-9b7c-d5fcae087e10` C=1；复审 `fa56c0df-0526-4a9c-aefa-a6cf65318856` → Approved C/I=0。
- **Human edits：** none
- **红灯：** `my file.txt` 被拆成 `file.txt`；`"a/\344\270\255..."` 被解成 `344270255....txt`，全 pre recover 误标 applied。
- **绿灯：** `tests/test_apply_back.py` **16 passed**；全量 **217 passed, 2 skipped**。
- **Follow-up commit：** `ec33655b6b38eaf33da7c30e2251cad5ad049e7a`
---

## 2026-08-14 · T21 只读文件工具（WT-F）

- **Task：** T21（WT-F / `feat/f-tools`）。未执行 T22（本条仅 T21）。
- **Implementer：** 原实现 `bf019fe`；续跑 owner `8f380e59-0ee8-47a9-b0f6-2f489643fe08`
- **Spec reviewer：** 初审 `2759c690` C=0 I=2；复审 `de375c50` C=0 I=2；终审 `e7bef377` C=0 I=0 Approved。
- **Quality reviewer：** 前轮 `0ccafa24` C=2 I=4；复审 `9520c5d5`（head `3dcf1d7`）C=0 I=4，其中 I1/I4 已在 `e5a085b` 修；I2 大文件提前 return、I3 截断 UTF-8 丢前缀、空 query 在后续 fix 修。
- **Human edits：** none
- **红灯：** 缺失模块 / 行范围 / `.env` 名 / `read_paths` / `.git`（`.superpowers/sdd/t21-red.txt`、`t21-fix-red.txt`）
- **绿灯：** T21 目标 26+；全量当时 **206 passed, 2 skipped**；后续累计见 T24。
- **实现 commit：** `bf019feeda436e200cbe1f173904c4c591e2634d`
- **修复 commits：** `3dcf1d72cbd2797c3c4b780cab4449e684b028fe`；`e5a085b6b8b794381b5db83e72b152be50f0aac5`；`27fd75d`（空 query、大文件不中断后续命中、截断 UTF-8 保留前缀）

---

## 2026-08-14 · T22 apply_patch 管线（WT-F）

- **Task：** T22。未执行 T23（本条仅 T22）。
- **Implementer：** `8f380e59-0ee8-47a9-b0f6-2f489643fe08`
- **Spec reviewer：** 初审 `0538683d` C=1 I=2；终审 `670c0e6f` C=0 I=0。
- **Quality reviewer：** `6db4ea3b` C=2 I=4（空行 hunk、纯 rename、回滚、nofollow、覆盖）；`\ No newline` 在 `-` 行后误剥已在后续 fix 修。
- **Human edits：** none
- **红灯：** `ImportError: PatchError`（`.superpowers/sdd/t22-red.txt`）
- **绿灯：** `test_apply_patch` 7 passed / 1 skipped；全量当时 **213 passed, 3 skipped**
- **实现 commit：** `b1794699ed25c1d6f2b457105be5a89964d19eca`
- **修复 commit：** `fef178488696bf09f7e5a7f6a22b827da48bf622`；`27fd75d`（`-` 行后 `\\ No newline` 不剥上一行）

---

## 2026-08-14 · T23 run_command + `{junit_out}`（WT-F）

- **Task：** T23。未执行 T24（本条仅 T23）。
- **Implementer：** `8f380e59-0ee8-47a9-b0f6-2f489643fe08`
- **Spec reviewer：** `6679e800` C=0 I=0 Approved。
- **Quality reviewer：** `da7cc7ed` C=0 I=0；Minor：测试未钉死 `shell=False`；`capture_output` 先收全量再截断。
- **Human edits：** none
- **红灯：** `ModuleNotFoundError: command_result`（`.superpowers/sdd/t23-red.txt`）
- **绿灯：** `test_run_command` 6 passed；全量当时 **219 passed, 3 skipped**
- **实现 commit：** `92f711a2edaca5605b44a306a58ef28b8eda9f5c`

---

## 2026-08-14 · T24 M5 executor + 排他 retry claim（WT-F）

- **Task：** T24。未执行 T25。未合并 PR-F。
- **Implementer：** `8f380e59-0ee8-47a9-b0f6-2f489643fe08`
- **Spec reviewer：** `f9e740e8` C=0 I=0。
- **Quality reviewer：** `9b79b77a` C=1 I=2（不同 `attempt_id` 拆排他；claim 先于 apply 消费；读工具可复用 apply 窗）。对抗 `41cc8804` 同 C=1，另指出 `run_command` 未关窗会再跑。均已在 `f90872b` 修。
- **分支审查：** Spec `f3ce8a10` C=1 I=2（Action 未绑窗口镜像；`allow_delete` 未接线；claim 不要求 `execution_started`）；Quality `fea1c056` C=0 I=5（其中 claim/kind 已在 `f90872b` 修；剩余尾部 rename、symlink 当删除、`read_file` 无界 readline）。
- **硬门槛测试 1–8：** 双连接仅一 claim；双 recover 不得双执行；无 claim 零写盘；错/旧 claim 拒绝；claim 一次性；混合 pre/post error；run_command recover 不重跑；正常 permit 路径无需 claim。均已通过。
- **Human edits：** none
- **红灯：** 缺 `executor` / `claim` / `UnauthorizedError`
- **绿灯：** `test_executor` 初版 10 passed；I1 修复后 19 passed / 1 skipped；全量 **249 passed, 4 skipped**
- **实现 commit：** `7afede0369ac0326931d07cee16139161718f110`
- **复审：** Quality `0b525676` C=0 I=0；Spec `8cb88b05` C=0 I=1（未启动窗带无效 `claim_id` 先写盘）已修：首次 apply 若带 `claim_id` 在写盘前拒绝。
- **推送：** `feat/f-tools`（不合并、不执行 T25）
---

## 2026-08-14 · T40 秘密扫描（WT-M）

- **Task：** T40（WT-M / `feat/m-release` / `.worktrees/wt-m-release`）。未执行 T41。未合并 PR-M。
- **Implementer：** 继承未提交实现（前 owner API limit）；Lane M owner `lane-m-owner` 续跑审查/修复/提交。
- **Spec reviewer：** 初审 `93b59e55-cbb9-4f9b-8f99-fac2aba11f00` → Spec ✅；复审 `06f571ac-7875-4772-94d8-6ca554680e3a` → Spec ✅。C/I=0。
- **Quality reviewer：** 初审 `b53a6c9c-69de-4445-88c1-90c0619c9454` Needs fixes（I=2：缺嵌套目录对照、路径未 resolve）；复审 `42c9383a-5b79-4fe3-a750-dda02c4f0ab7` → Approved。C/I=0。
- **Human edits：** none
- **红灯：** 仅有 `tests/test_secret_scan.py` 时 collection `ImportError: No module named 'scripts'`（`.superpowers/sdd/t40-red.txt`）。
- **绿灯：** 初版 targeted 37 passed；I=2 修复后 targeted 38 passed；全量 **206 passed, 2 skipped**。
- **实现 commit：** `ed0c8472335ba953cba7713731a5295d214c394d`（含 `test_config_load.py` PEM 头拼接卫生）。
- **Minors（不修）：** stripe/gitlab/ASIA/github_pat/非通用 PEM 头无专测；`.cache`/`htmlcov` 未参数化；symlink 与 walk onerror 无测。

---

## 2026-08-14 · T41 CI（WT-M）

- **Task：** T41（WT-M / `feat/m-release`）。未执行 T42/T43。未合并 PR-M。
- **Implementer：** Lane M owner `lane-m-owner`
- **Spec reviewer：** 初审 `dfe2102b-9144-4546-a35f-27436dd4eaf4` → Spec ✅；复审 `8433b255-56bc-4fc6-ae75-8c556380278c` → Spec ✅。C/I=0。
- **Quality reviewer：** 初审 `5ac9d85c-b485-41ad-adcc-2f7ca2a68766` Needs fixes（I=2：SHA-256 子串过弱、`unit-test:`/`combined` 假绿）；复审 `24ca1d23-b361-4aa1-9b10-01f89a0bee3c` → Approved。C/I=0。
- **Human edits：** none
- **红灯：** 仅有 `tests/test_ci_files.py` 时 4 failed，缺 `.github/workflows/ci.yml` / `release.yml` / `.gitlab-ci.yml`（`.superpowers/sdd/t41-red.txt`）。
- **绿灯：** targeted 4 passed；本地 `python scripts/secret_scan.py .` → clean 78 files；本地 `python -m build --wheel` → `guardedcoder-0.1.0-py3-none-any.whl`。
- **实现 commit：** `e757a9d47700dc9928c79e77b2e217106f7cdefc`
- **Minors（不修）：** Actions/镜像未钉 commit digest；SHA-256 仍是 token 子串；CI 测试未强制断言 `push:`。
- **未声称** 远程 CI 已 pass。未创建真实 tag/Release。

---

## 2026-08-14 · Codex PR-M integration follow-up

- **Trigger:** GitHub Actions run `31767433383` failed in strict hash mode because the Windows-generated lock omitted keyring's conditional Linux `SecretStorage` dependency.
- **Change:** declared `SecretStorage` explicitly, regenerated both pip-tools hash locks with the frozen PyPI command, and added a regression assertion for the Linux backend.
- **Verification:** full suite `211 passed, 2 skipped`; secret scan clean (78 files); wheel build passed; a fresh Windows Python 3.12 environment installed `requirements-dev.txt` with `--require-hashes` successfully.
- **Human edits:** Codex integration fix requested and approved by the project owner.

---

## 2026-08-14 · Codex PR-F credential-redaction follow-up

- **Trigger:** integration review found that Observation and audit redaction only recognized `sk-` credentials.
- **Change:** introduced a shared sanitizer for common provider tokens, labeled opaque secrets, Bearer authorization values, and private-key material; Observation uses a bounded short replacement while audit uses `[redacted]`.
- **Red/green:** the first implementation exposed an Observation byte-budget regression (`1 failed, 19 passed`); the bounded replacement fixed it. Targeted `20 passed`; full suite `284 passed, 4 skipped`; secret scan clean (95 files).
- **Human edits:** Codex integration fix requested and approved by the project owner.


---

## 2026-08-14 · Lane I integration and discard ownership hardening (Codex)

- **Agent / model:** Codex (current task; integration review and fix).
- **Human edits:** none.
- **Scope:** combined main's recovered-claim / `execution_started` schema with Lane I's nullable apply-back permit / fingerprint schema; rejected symlink, Windows junction, and non-exact registered worktree paths.
- **Migration evidence:** legacy F schema keeps its recovery claim, gains nullable permit plus both fields, and passes `PRAGMA foreign_key_check`.
- **Discard evidence:** aliases fail closed before `git worktree remove`; the lexical path must also appear in `git worktree list --porcelain -z`.
- **Tests:** targeted `27 passed`; integrated full suite `323 passed, 4 skipped`.


