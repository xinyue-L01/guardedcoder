# REFLECTION

> 初稿由项目所有者撰写。AI 仅做语句润色，并按 AGENT_LOG / G2 记录补入可核对的数字与裁决；未编造未亲历情节。

## 1. 为什么选择 coding agent harness

我选择 coding agent harness，是因为它比普通 chatbot 更能落到「智能体如何真正作用于软件工程环境」这个问题上。课程要求的不只是调用模型，而是自己实现决策、工具、记忆、治理、反馈和配置。GuardedCoder 因此被收窄为本地、单仓库、单任务 CLI：LLM 可以读代码、改文件、跑命令，但这些能力必须可控、可验证、可恢复。不是再做一个 Cursor 替代品。

## 2. 最初对安全 / 治理的理解

项目早期，我对「安全」的理解更接近限制工具和列禁止项：不让模型 push、不让它碰敏感文件，危险操作再让用户确认。brainstorming 之后才意识到这仍然太粗。真正的问题不只是某个动作「危险不危险」，而是它是否仍发生在被批准的 task、信封版本、base commit、worktree 和状态上。治理因此从 deny-list，变成对执行上下文和状态转换的约束。

## 3. Brainstorming 中被迫澄清的关键边界

brainstorming 最有价值的地方，是把模糊承诺改成可失败的硬边界。原工作树不干净就拒绝启动，不允许 HITL 后再继续；文件工具围栏不等于 OS 沙箱；已确认 profile 在宿主机以当前用户权限运行，因此不能宣称子进程完全断网；API Key 只进 keyring，不进仓库、日志和信封；配置只能合成信封，不能关闭硬拒绝。安全设计首先要写清系统保证什么、明确不保证什么。

## 4. 为什么治理成为 main contribution

「能调用 LLM」并不难，难的是让副作用和用户批准保持同一性。动作指纹绑定 task、envelope、base commit、worktree identity 和规范化动作；审批还绑定 pending action 与 state revision；真正执行前签发一次性 permit，必须先消费 permit、打开 execution window，工具层才允许产生副作用。未确认信封则不建 worktree、不调 LLM。机制演示用 MockLLM、无 Key、无网络，连续两次 exit 0 且输出字节级一致。这比在提示词里写「不要做危险操作」更接近 harness 核心。

## 5. 冷启动 OpenCode 暴露的 SPEC / PLAN 缺陷

G0 第一次检验「陌生智能体只看 SPEC 和 PLAN 能不能开工」。执行者是 OpenCode（glm-5.2）：全新 session，不导入历史或 memory，仓库外 disposable 试做 T01+T02，约 43 分钟，终态 4 passed。它卡在 pyproject 构建字段、包导入边界、Windows 测试命令、pip-tools 的 index 和 StrEnum 枚举全集。我据此把 setuptools、`python -m pytest`、固定 PyPI lock 和枚举要求写死，未把 disposable 源码复制进正式仓，并在签署 G0 通过后才授权 G1；G1 本身不执行 T01。设计者觉得「显然」的东西，对冷启动实现者并不显然。

## 6. Cursor / Codex / OpenCode / 子智能体如何分工

这个项目不是让多个智能体替我做决定，而是刻意分角色。Cursor Agent + Superpowers 负责主开发编排，具体实现交给不同 subagent。Spec Review 检查有没有按签字设计实现，Quality Review 检查实现是否可靠。Codex 见过完整设计史，因此不能充当 G0 冷启动，只做独立审查和反例。OpenCode 承担真正的冷启动和后期独立外审。我是 owner：确认范围、签 SPEC 和 G0、决定哪些审查必须修、哪些推迟，并对 Release 负责。实现源码全程 Human edits 为 none，不等于没有人工工作——裁决本身就是工作。

## 7. TDD、Spec Review、Quality Review 如何发现真实问题

TDD 和两阶段审查发现的是「代码能跑但语义不对」。T03 要 `strict=True` 并收紧 oversized 路径，T04 的 `argv_template` 仍是可变 list，都是 Quality Review 后才修掉。后置检查同样打穿过绿灯：T39 机制演示本地已绿，CI 子进程没有 `PYTHONPATH` / editable install，无法 `import guardedcoder`；T43 离线 E2E 初红 10 failed——越 write_paths 的 `apply_patch` 在 `evaluate()` 里被误判 Allow，HITL 走不到产品路径，直到把 `classify_write` 接进评估才 10 passed；T42 文档审计初红 6 failed，README 未按 SPEC 列第三方许可证。终态全量 500 passed、4 skipped。不同层次的红灯覆盖不同盲区。

## 8. 最困难的 bug

最困难的不是语法错误，而是 permit、执行窗口和崩溃恢复的并发语义。PR-E 第一轮 Codex 反例直接打出 stale permit（envelope 不变、revision 变后仍能 consume，DID NOT RAISE）、双窗口、跨进程状态丢失和恢复路径逃逸。第二轮更关键：reviewer 提出新 revision 可能再次认领同一恢复窗口，以及 pre/postimage 路径集合问题；controller 一度准备依据已有语义驳回，反例证明这个判断不成立。

我没有为了消审查意见在 `recover()` 里伪造 claim，也没有把 I1 标成 won't fix。真正的排他 retry claim 被写成 T24 / M5 集成硬门槛：无有效 claim 必须拒绝，claim 不可重放；完成前 T24/T28 不得标 done。安全机制不能靠「我觉得语义应该如此」裁决，必须让反例跑起来。

## 9. 哪些功能没有做，为什么

我砍掉了 WebUI、云部署、多 agent 编排、自动 commit/merge/push、OS 级进程沙箱、子进程网络隔离、向量记忆和任意 shell。不是这些功能没有价值，而是它们会迅速扩大攻击面，削弱治理主线。glm-5.2 独立外审（未参与实现）结果是 Critical = 0、Important = 3：信封展示缺「原树是否干净 / 真实路径」、业务异常打到 stdout、部分 resume 只走一步。Q-I3（resume 重跑已开始的 `run_command`）已由 T43 闭环。硬边界、Key、permit、审批、原树和重跑没有被打穿。3 项 Important 记为已知限制，推迟到 v0.1.1，本回合不改代码、不开修复 PR。

## 10. 我作为 human owner 做了哪些决策和裁决

最重要的人工工作不是手写业务代码，而是边界裁决。我否决了「脏树经 HITL 继续」「LLM 直接写长期记忆」「配置可以放宽硬规则」「把文件围栏宣传成 OS 沙箱」。G0 由我签署后才进入正式实现。PR-E 争议上，我接受反例推翻原判断。面对外审，我接受 3 项非安全 Important 为 v0.1.1 已知限制，并发布 v0.1.0。Release wheel 的 SHA-256 与 sidecar、本地下载 `Get-FileHash` 一致，只证明文件与发布声明一致，不是签名、不能抵御平台失陷。pipx 安装后 `auth status` 无配置时非 0，无明文 Key。机制演示两次离线跑通。

Human-Owned 不是最后点一下同意，而是对范围、证据、例外和风险承担最终责任。

## 11. 如果重做一次

如果重做一次，我会更早把「恢复与并发」做成最小原型，在大规模实现前先验证 SQLite 事务、state revision、permit、execution window 和 retry claim 的组合语义。同时更早在 Linux CI 上验证 hash lock 和子进程安装环境。流程上仍保留 SPEC 签字、冷启动、TDD 和双 reviewer，但会减少可被不同人读成不同含义的自然语言，把关键约束直接写成状态表、前后条件和反例测试。

## 12. 对 Spec-Driven、Subagent-Built、Human-Owned 的理解

做完以后，这三个词变得可执行。Spec-Driven 是实现和审查都能追溯到已签字的不变量；Subagent-Built 是把实现、Spec Review、Quality Review、冷启动和外审拆成相互制衡的角色，而不是「让 AI 自动做完」；Human-Owned 是最终范围、例外、延期和 Release 必须由我根据证据裁决。

GuardedCoder 让我学到的，不是怎样让 agent 获得更多自主权，而是怎样在给予它实际能力的同时，让这种自主始终处在可解释、可验证、可恢复、可停止的边界之内。
