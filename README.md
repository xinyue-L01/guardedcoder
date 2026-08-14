# GuardedCoder

CLI harness：把边界清楚的小编码任务交给 LLM，同时用确定性代码做路径围栏、策略信封、动作指纹、一次性执行许可、HITL 与 verify。成功时默认只给出完整 patch，不自动改用户原工作树。

仓库：https://github.com/xinyue-L01/guardedcoder

本产品是 **CLI-only**；**无 WebUI**；**无云部署**；**无单文件 exe**。

## 产品简介

`guardedcoder` 在已初始化的本地 Git 仓库上跑单个任务。LLM 只能输出五类工具（`list_dir` / `read_file` / `search_text` / `apply_patch` / `run_command`）或 `finish`。治理在 harness 内，不依赖提示词，也不使用 agent framework。

## 安装

前提：**Python 3.12+** 与 **系统 Git**。启动会检查二者。

源码可编辑安装（开发）：

```text
python -m pip install --require-hashes -r requirements-dev.txt
python -m pip install -e .
```

发布 wheel（发布后填写真实 GitHub Release 资产 URL，再替换占位）：

```text
pipx install <release-wheel-url>
pipx upgrade guardedcoder
pipx uninstall guardedcoder
```

不要用真实 API Key 做安装冒烟；先 `guardedcoder --help`。

## config

用户 TOML 在 OS 配置目录：`guardedcoder/config.toml`（Windows 为 `%APPDATA%`）。硬拒绝规则由代码定义，TOML 与 CLI 不能关闭或放宽。

```text
guardedcoder config init
guardedcoder config validate
guardedcoder config show
```

`init` 写合法模板；`validate` 只校验不启动任务；`show` 只打印非敏感配置。

## auth

API Key **只进 keyring**（Windows Credential Manager / macOS Keychain / Linux Secret Service）。**TOML/.env 不放 Key**；**不自动**加载 **.env**；keyring 失败不回退明文文件。

```text
guardedcoder auth set
guardedcoder auth status
guardedcoder auth update
guardedcoder auth clear
```

`set` / `update` 隐藏输入；`status` 不含明文。

## run 与信封确认

```text
guardedcoder run --repo <git-repo> --task "<任务描述>"
guardedcoder run --repo <git-repo> --task "<任务描述>" --confirm-envelope-hash <hash>
```

未加 `--confirm-envelope-hash` 时只合成并展示信封，**不建 worktree、不调 LLM**。已确认版本不可变；扩大范围必须新版再确认。原工作树必须干净，否则拒绝启动。

## HITL approve/reject/resume

审批一次性，且必须同时给出 `task_id` 与动作指纹：

```text
guardedcoder approve <task_id> <fingerprint>
guardedcoder reject <task_id> <fingerprint>
guardedcoder resume <task_id> <fingerprint>
```

上下文变化后旧批准失效。`resume` 恢复校验失败则进入 error。

## apply/discard

```text
guardedcoder apply <task_id>
guardedcoder apply <task_id> --confirm
guardedcoder discard <task_id>
```

`apply` 仅在 `succeeded` + `patch_ready` 时可用；**确认前不改原树**。`discard` 丢弃任务 worktree，不把补丁打回原树。完整 patch **不静默截断**；超总变更上限则不能形成可 apply 的成功产物。

## memory

仓库级结构化记忆，不能放宽策略，也不能当授权来源：

```text
guardedcoder memory add --repo-id <id> --type <type> --content <text>
guardedcoder memory list --repo-id <id>
guardedcoder memory export --repo-id <id>
guardedcoder memory clear --repo-id <id>
```

## 机制演示

离线四场景（护栏、FAIL 门控反馈、指纹/permit/窗口、非法 TOML），不扩工具面、不访问网络：

```text
python demos/mechanism_demo.py
```

## 分发

源码与 Release 平台均为 GitHub。构建带版本号的 wheel，校验和用 `scripts/hash_wheel.py`（与 `hashlib.sha256` 一致）。GitHub Actions 在 tag 上构建并上传；本 README **不声称** Release 已存在。资产 URL **发布后填写**。

## 项目目录结构

```text
pyproject.toml
requirements.in / requirements-dev.in
requirements.txt / requirements-dev.txt   # pip-tools --generate-hashes
LICENSE
THIRD_PARTY_LICENSES.md
src/guardedcoder/          # CLI、config、auth、loop、governance、tools、persist
demos/mechanism_demo.py
scripts/secret_scan.py
scripts/hash_wheel.py
tests/
.github/workflows/ci.yml
.github/workflows/release.yml
.gitlab-ci.yml             # 含 unit-test job
```

## 安全边界

文件工具围栏 ≠ 操作系统沙箱。本产品 **无 OS 网络/文件系统沙箱**；command / verify **profile 在宿主机以当前用户权限执行**。不向 LLM 提供通用网络工具；push / 发布 / 部署为产品级硬拒绝。仓库和 profile **可信**是威胁前提：用户应选择无网络副作用的 profile。

## 源码离机隐私

真实 LLM 会发送任务描述、选中源码片段、记忆和 observation。首次使用及信封确认须明示 endpoint 与将离机数据类型。不承诺对 provider 侧保密；敏感路径不要进入上下文，或改用本地兼容 endpoint。

## 凭据威胁模型

| 威胁 | 对策 |
|---|---|
| Key 写入源码 / Git / TOML | 禁止；schema 拒绝 secret-like 字段 |
| Key 进 `.env` / 明文文件 | 不自动加载 `.env`；keyring 失败不回退文件 |
| `status` / 日志 / 异常泄露 | 无明文；审计脱敏 |
| 记忆或提示词“授权” | 记忆不能放宽策略；无读 key 工具 |
| 配错 endpoint | 携带 Key 的远程 `base_url` 必须 HTTPS；HTTP 仅 loopback；不跟随跨 origin 重定向 |

无 Web 服务，无远程会话存 key。

## 已知限制

- CLI-only；无 WebUI；无云部署；无单文件 exe
- 无 OS 网络/文件系统沙箱；无子进程网络隔离
- 单仓库、单任务、单 worktree；不自动 stash / commit / push / merge
- 无向量记忆；LLM 不能直接改长期记忆
- profile 内部仍可能联网或做额外事（前提是仓库和 profile 可信）

## 开发与测试

权威命令（Windows 不以 make 为前提）：

```text
python -m pytest
python scripts/secret_scan.py .
python -m build --wheel
python scripts/hash_wheel.py dist/*.whl
```

依赖锁定只用 pip-tools + `--generate-hashes`，不用 `pip freeze` 作为交付锁文件。

## GitHub Release 与 SHA-256 校验

仓库：https://github.com/xinyue-L01/guardedcoder

Release 资产 URL：**发布后填写**（不要伪造尚未创建的 tag 或资产链接）。

安装示例（占位）：`pipx install <release-wheel-url>`

校验：对下载的 `.whl` 运行 `python scripts/hash_wheel.py <wheel>`，将打印的 hex 与 Release 上的 `.sha256` / 发布说明比对。

**SHA-256 只核对文件与发布声明一致，不能抵御托管平台整体失陷。** 它不是签名，也不能证明 GitHub 或镜像本身未被整体替换。
