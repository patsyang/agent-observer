# Agent Observer 问题观测能力提升 PRD

> 版本：v1.0  日期：2026-06-30
> 范围：被观测 Agent 的问题识别能力（不涉及 agent-observer 自身健康观测）

## 1. 背景与目标

agent-observer 的核心价值是"观测被托管 Agent 的问题"。2026-06-30 代码审计发现当前问题识别体系存在三类失效：

- **识别错误**：把业务门禁阻断误判为工具失败；敏感内容扫描字段选错导致从未命中
- **识别缺失**：Agent 重复犯错、卡循环、用量异常等核心场景无 signal
- **机制失效**：关键文件硬编码针对自身项目；决策不回流

本 PRD 目标：建立通用、准确、可反馈的问题识别体系，使 agent-observer 能正确识别被观测 Agent 的真实问题，不误报、不漏报关键场景。

## 2. 问题定义

### 2.1 识别错误（P0）

| 编号 | 问题 | 当前行为 | 期望行为 |
|---|---|---|---|
| P0-A | 敏感内容扫描字段错误 | 扫描 command/path/workdir/payload_name 4 个不可能命中的字段，输出/响应/推理完全没扫 | 扫描工具输出、响应内容、推理内容 |
| P0-A | 敏感内容正则太宽 | `token` 关键字 + 16 位字符即命中，`access_token=` 这种变量名也会触发 | 基于密码学前缀和结构特征，不基于关键字 |
| P0-B | 工具失败子类型混杂 | 4 种语义（脚本崩溃/业务门禁/校验失败/子步骤透传）全归 tool_execution_failure，priority=95 | 按输出语义拆分，不同 priority |

### 2.2 识别缺失（P1）

| 编号 | 问题 | 当前行为 | 期望行为 |
|---|---|---|---|
| P1-A | Agent 重复犯错 | 同签名 N 次失败被聚合成 1 个 signal，掩盖"反复"语义 | 达阈值后生成独立 repeated_tool_failure signal |
| P1-B | Agent 卡循环 | 无 progress 信号 | 会话长时间无 content 但有工具调用时告警 |
| P1-C | 用量异常无运行期 signal | 仅 dashboard + 发布前 validation | 运行期生成 usage_spike / low_cache_hit_rate signal |

### 2.3 机制失效（P2）

| 编号 | 问题 | 当前行为 | 期望行为 |
|---|---|---|---|
| P2-A | 关键文件硬编码 | KEY_PATH_PATTERNS 写死 agent-observer 自身的 5 类路径 | 可配置，默认覆盖通用项目结构 |
| P2-B | 决策不回流 | conclusion_code 4 档，不影响 priority | 扩档 + 同签名多次决策后降权 |

## 3. 解决方案

### 3.1 P0-A：敏感内容识别修正

#### 3.1.1 设计原则

1. **基于结构特征，不基于关键字**：所有识别规则必须基于数据本身的格式特征（前缀、长度、字符集、结构、校验算法），不允许以 "token" / "secret" / "auth" 等关键字作为独立判定依据
2. **校验算法优先**：能通过校验算法（Luhn、身份证校验位）验真的，必须加校验，校验失败不识别
3. **只识别高置信度类型**：宁可漏报低风险数据，不可误报
4. **排除占位符**：`<your-api-key>` / `xxx` / `example` / `test` / `sample` / `${ENV_VAR}` 等占位符不识别

#### 3.1.2 识别规则

按 6 大类组织，共 25 种识别类型，全部置信度 high（接近 100% 准确）：

**A. API Keys / Tokens（云服务/开发平台，15 种）**

| 类型 | 正则特征 | 依据 |
|---|---|---|
| OpenAI API Key | `sk-proj-[A-Za-z0-9_-]{40,}` 或 `sk-[A-Za-z0-9]{48}` | OpenAI 官方：sk- 前缀 + 48 位 base62 |
| Anthropic Key | `sk-ant-[A-Za-z0-9_-]{50,}` | Anthropic 官方：sk-ant- 前缀 |
| Google API Key | `AIza[A-Za-z0-9_-]{35}` | Google 官方：AIza 前缀 + 35 位 |
| AWS Access Key ID | `AKIA[0-9A-Z]{16}` 或 `ASIA[0-9A-Z]{16}` | AWS 官方：AKIA/ASIA + 16 位大写 |
| Azure SAS Token | `sig=[A-Za-z0-9%]{43,}` | Azure 官方：URL 编码的签名，43+ 字符 |
| HuggingFace Token | `hf_[A-Za-z0-9]{34}` | HuggingFace 官方：hf_ 前缀 + 34 位 |
| GitHub Token | `gh[pousr]_[A-Za-z0-9]{36}` | GitHub 官方：ghp_/gho_/ghu_/ghs_/ghr_ + 36 位 |
| GitLab Token | `glpat-[A-Za-z0-9_-]{20}` | GitLab 官方：glpat- 前缀 + 20 位 |
| Slack Token | `xox[abprs]-[A-Za-z0-9-]{10,}` | Slack 官方：xoxb-/xoxp-/xoxa- 等前缀 |
| Stripe Key | `sk_(live\|test)_[A-Za-z0-9]{24,}` 或 `rk_live_[A-Za-z0-9]{24,}` | Stripe 官方：sk_live_/sk_test_/rk_live_ 前缀 |
| DigitalOcean Token | `dop_v1_[a-f0-9]{64}` | DigitalOcean 官方：dop_v1_ + 64 位 hex |
| npm Token | `npm_[A-Za-z0-9]{36}` | npm 官方：npm_ 前缀 + 36 位 |
| Shopify Token | `shp[at\|ss\|ca\|pa]_[a-fA-F0-9]{32}` | Shopify 官方：shpat_/shpss_/shpca_/shppa_ + 32 位 hex |
| Twilio API Key | `SK[0-9a-fA-F]{32}` | Twilio 官方：SK 前缀 + 32 位 hex |
| SendGrid API Key | `SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}` | SendGrid 官方：SG. + 两段 base64 |

**B. 密钥（1 种）**

| 类型 | 正则特征 | 依据 |
|---|---|---|
| PEM 私钥 | `-----BEGIN (RSA\|EC\|OPENSSH\|PGP\|) PRIVATE KEY-----` | PEM 标准 RFC 7468，确定性 100% |

**C. 令牌（1 种）**

| 类型 | 正则特征 | 依据 |
|---|---|---|
| JWT | `eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}` | JWT 三段式 base64 结构（header.payload.signature） |

**D. 认证头（2 种）**

| 类型 | 正则特征 | 额外校验 |
|---|---|---|
| Bearer Token | `[Bb]earer [A-Za-z0-9_-]{20,}` | token 部分长度 >= 20 |
| Basic Auth | `[Bb]asic [A-Za-z0-9+/=]{16,}` | base64 解码后含冒号（user:password 格式） |

**E. 支付（1 种，需校验算法）**

| 类型 | 正则特征 | 校验算法 |
|---|---|---|
| 银行卡号 | `\b[0-9]{13,19}\b` | **Luhn 校验**：从右到左，奇数位相加，偶数位乘 2 后相加，总和对 10 取模为 0 |

Luhn 算法排除 90%+ 的随机数字串误报（订单号、时间戳、ID 等）。

**F. 身份信息（2 种，需校验算法）**

| 类型 | 正则特征 | 校验算法 |
|---|---|---|
| 中国身份证号 | `\b[1-9]\d{5}(19\|20)\d{2}(0[1-9]\|1[0-2])(0[1-9]\|[12]\d\|3[01])\d{3}[0-9Xx]\b` | **ISO 7064 MOD 11-2 校验位**：前 17 位 × 权重 [7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2] 求和 mod 11，映射到 ['1','0','X','9','8','7','6','5','4','3','2'] |
| 中国手机号 | `1(3\d\|4[5-9]\|5[0-35-9]\|6[2567]\|7[0-8]\|8\d\|9[0-35-9])\d{8}` | **运营商号段**：前 3 位必须匹配已分配号段（130-139/145-149/150-159/162,165-167/170-178/180-189/190-199） |

**G. 连接串（2 种，需额外校验）**

| 类型 | 正则特征 | 额外校验 |
|---|---|---|
| 数据库连接串 | `(postgres\|mongodb\|mysql\|redis)://[^:\s]+:[^@\s]+@` | 密码部分不能是占位符（`<...>` / `${...}` / `xxx` / `password` / `your_password`） |
| Azure Storage 连接串 | `AccountKey=[A-Za-z0-9+/=]{50,}` | AccountKey base64 长度 >= 50（真实 key 约 88 字符） |

#### 3.1.3 敏感路径访问识别

新增维度：当 Agent 访问或输出系统级敏感文件时识别为敏感内容暴露。基于路径模式匹配，不基于文件内容。

**Linux 高敏感路径**：

| 路径模式 | 说明 |
|---|---|
| `/etc/shadow` / `/etc/gshadow` | 密码哈希 |
| `/etc/passwd` / `/etc/group` | 用户/组信息 |
| `/etc/sudoers` / `/etc/sudoers.d/*` | sudo 配置 |
| `/etc/ssh/sshd_config` / `/etc/ssh/ssh_config` | SSH 服务端/客户端配置 |
| `/root/.ssh/*` / `~/.ssh/id_*` / `~/.ssh/authorized_keys` | SSH 私钥/公钥/授权 |
| `/etc/ssl/private/*` / `/etc/letsencrypt/*` | SSL 私钥/证书 |
| `/etc/environment` / `/etc/profile.d/*` | 系统环境变量 |
| `/var/log/auth.log` / `/var/log/secure` | 认证日志 |
| `/proc/self/environ` / `/proc/<pid>/environ` | 进程环境变量（可能含密钥） |
| `~/.aws/credentials` / `~/.aws/config` | AWS 凭据 |
| `~/.kube/config` | Kubernetes 凭据 |
| `~/.docker/config.json` | Docker 凭据 |
| `~/.netrc` / `~/.git-credentials` | HTTP/Git 凭据 |
| `~/.npmrc`（含 `_authToken`） | npm 凭据 |
| `~/.pypirc` | PyPI 凭据 |
| `~/.gnupg/*` | GPG 密钥环 |
| `/etc/crontab` / `/etc/cron.d/*` | 定时任务 |
| `/etc/nginx/*`（含 ssl_certificate 等） | Nginx 配置 |
| `/etc/kubernetes/*` / `/etc/docker/daemon.json` | 容器/K8s 配置 |

**Windows 高敏感路径**：

| 路径模式 | 说明 |
|---|---|
| `C:\Windows\System32\config\SAM` | 安全账户管理器 |
| `C:\Windows\System32\config\SYSTEM` / `SECURITY` / `SOFTWARE` | 注册表配置单元 |
| `%USERPROFILE%\.ssh\id_*` / `authorized_keys` | SSH 私钥/公钥 |
| `%USERPROFILE%\.aws\credentials` / `config` | AWS 凭据 |
| `%USERPROFILE%\.kube\config` | Kubernetes 凭据 |
| `%USERPROFILE%\.docker\config.json` | Docker 凭据 |
| `%USERPROFILE%\.netrc` / `.git-credentials` | HTTP/Git 凭据 |
| `%APPDATA%\npm\.npmrc`（含 `_authToken`） | npm 凭据 |
| `%LOCALAPPDATA%\Microsoft\Credentials\*` | Windows 凭据管理器 |
| `%APPDATA%\Microsoft\Protect\*` | DPAPI 主密钥 |
| `C:\ProgramData\Microsoft\Crypto\*` | 加密密钥 |
| `%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt` | PowerShell 历史（可能含明文密码） |

**通用敏感文件名（跨平台）**：

| 文件名 | 说明 |
|---|---|
| `.env` / `.env.local` / `.env.production` / `.env.staging` | 环境变量文件 |
| `id_rsa` / `id_ed25519` / `id_ecdsa` / `id_dsa` | SSH 私钥 |
| `id_rsa.pub` / `id_ed25519.pub` | SSH 公钥（低风险，仅标注） |
| `credentials` / `credentials.json` | 通用凭据文件 |
| `.htpasswd` | Apache 密码文件 |
| `*.kdbx` | KeePass 数据库 |
| `secrets.yml` / `secrets.json` / `secrets.yaml` | 通用密钥文件 |
| `wp-config.php` | WordPress 配置（含数据库密码） |

**识别规则**：
- 命令参数（command/path/workdir）包含上述路径模式 → 标注 sensitive_path_access
- 工具输出包含上述文件的内容 → 标注 sensitive_content_exposure
- 路径匹配使用规范化处理（统一正斜杠/反斜杠、解析 `~` 和环境变量）

#### 3.1.4 扫描字段

| 字段 | 来源 | 优先级 | 说明 |
|---|---|---|---|
| 工具输出 | function_call_output.output | 高 | `cat .env` / `curl` 响应 / 错误堆栈的主要载体 |
| Agent 响应内容 | agent_response.content | 高 | Agent 复述/处理敏感数据 |
| Agent 推理 | agent_reasoning.content | 高 | Agent 思考链引用敏感值 |
| 命令参数 | args.command / args.path / args.workdir | 高 | 敏感路径访问的主要识别来源 |
| payload.name | 工具名 | 低 | 保留现有扫描，作为补充 |

#### 3.1.5 误报控制

排除以下模式（即使匹配上述正则也不识别）：
- 占位符：`<your-api-key>` / `xxx...xxx` / `your_token_here` / `example` / `test` / `sample` / `placeholder`
- 环境变量引用：`${OPENAI_API_KEY}` / `$GITHUB_TOKEN`（名字本身不是值）
- 文档示例：`sk-xxxx...xxxx`（连续 x 占位）
- 长度不足：所有匹配必须达到该类型的最小长度（已在正则中体现）
- 校验失败：银行卡号 Luhn 校验不通过、身份证校验位不匹配、手机号前 3 位不在号段表内

#### 3.1.6 不识别的内容

明确排除以下场景，避免误报：
- 任意 `key=value` 形式的字符串（除非 value 匹配上述结构特征）
- 任意包含 "token" / "auth" / "secret" / "key" / "password" 关键字的文本（关键字不作为判定依据）
- 短于 16 位的字符串（除路径匹配外）
- 配置文件中的字段名（如 `OPENAI_API_KEY=` 后面为空或占位符）
- 测试 fixture 中的 mock 值
- SSH 公钥（`.pub` 文件内容，公钥本身不敏感）
- 邮箱地址（太通用，无法区分业务用途）
- 纯数字串（不经过 Luhn/校验位校验的数字不识别为银行卡/身份证）

---

### 3.2 P0-B：工具失败子类型拆分

#### 3.2.1 子类型定义

| 子类型 | signal_kind | 触发条件 | priority | 说明 |
|---|---|---|---|---|
| 脚本崩溃 | tool_execution_failure | 输出包含 traceback / errno / command not found | 95 | 真异常，需修复 |
| 业务门禁阻断 | workflow_gate_blocked | 输出是 JSON 且含 blocked=true / ok=false / gate=blocked | 30 | 预期返回，流程状态 |
| 校验失败 | validation_failure | 命令类别是 test/build/lint 且 exit_code!=0 | 60 | 预期反馈，非崩溃 |
| 其它工具失败 | tool_execution_failure | 不匹配上述模式 | 70 | 未知原因，需人工判断 |

#### 3.2.2 识别规则

**步骤 1：业务门禁阻断识别**
- 对 envelope.body 尝试 JSON 解析（取前 2000 字符）
- 命中以下任一字段组合即归类为 workflow_gate_blocked：
  - `ok=false` 且 `blocked=true`
  - `gate=blocked`
  - `status=blocked`
  - `result=blocked`
- 提取以下字段作为签名维度（如存在）：
  - `gate_id` / `gate`
  - `current_stage` / `stage`
  - `highest_blocker` / `blocker`
  - `workflow` / `process_file`

**步骤 2：脚本崩溃识别**
- 对 envelope.body 做错误模式匹配（不区分大小写）：
  - `Traceback (most recent call last)` → Python 异常
  - `ModuleNotFoundError` / `ImportError` → 依赖缺失
  - `FileNotFoundError` / `PermissionError` / `OSError` → 文件系统错误
  - `command not found` / `not recognized as an internal or external command` → 命令不存在
  - `No such file or directory` → 路径错误
  - `SyntaxError` → 语法错误
- 提取 error_type（traceback / import_error / file_error / command_not_found / syntax_error）作为签名维度

**步骤 3：校验失败识别**
- 命令类别（command_category）判定：
  - 包含 `pytest` / `vitest` / `jest` / `unittest` / `cargo test` / `go test` → test
  - 包含 `tsc` / `mypy` / `pyright` / `eslint` / `ruff` / `flake8` → lint
  - 包含 `npm run build` / `cargo build` / `go build` / `webpack` → build
- 命令类别属于 test/lint/build 且 exit_code!=0 → validation_failure

**步骤 4：fallback**
- 不匹配上述任何模式 → 保留 tool_execution_failure，priority 从 95 降为 70

#### 3.2.3 签名维度扩展

| signal_kind | 签名维度 | 说明 |
|---|---|---|
| workflow_gate_blocked | `category:tool:gate_id:current_stage:highest_blocker` | 不同 blocker 不聚合成同一 signal |
| tool_execution_failure（脚本崩溃） | `category:tool:error_type:exit_code` | 区分异常类型 |
| validation_failure | `category:tool:command_category:exit_code` | 区分 test/lint/build |
| tool_execution_failure（其它） | `category:tool:fingerprint:exit_code` | 保留原签名 |

#### 3.2.4 兼容性

- 已有 tool_execution_failure signal 不回溯重算
- 新 fact 按新规则分类
- 前端 signalLabels.ts 增加新 kind 的中文标签

---

### 3.3 P1-A：Agent 重复犯错识别

#### 3.3.1 识别规则

- 同一签名（command_fingerprint + exit_code）在同一会话内出现 >= 3 次
- 且该签名未被用户标记为 `accepted_risk` 或 `expected_nonzero_exit`
- 生成独立 signal：`repeated_tool_failure`

#### 3.3.2 签名维度

```
repeated_tool_failure:agent:workspace:conversation:tool:command_fingerprint:exit_code
```

#### 3.3.3 priority

- 80（高于单次失败，但低于敏感内容和脚本崩溃）
- 包含 occurrence_count 字段，展示重复次数

#### 3.3.4 不触发的情况

- 业务门禁阻断（workflow_gate_blocked）不触发重复犯错识别，因为多次 check-status 是预期行为
- 用户已标记 accepted_risk / expected_nonzero_exit 的签名

---

### 3.4 P1-B：Agent 卡循环识别

#### 3.4.1 识别规则

- 同一会话在 10 分钟内无新 content 事件（agent_prompt / agent_response / agent_reasoning）
- 但有持续的工具调用（function_call / function_call_output）或 usage 事件
- 表示 Agent 在反复调用工具但没有产出

#### 3.4.2 signal_kind

- `agent_loop_stuck`

#### 3.4.3 priority

- 75

#### 3.4.4 不触发的情况

- 会话正常结束（有 final agent_response）
- 会话空闲（无任何事件，可能是用户暂停）

---

### 3.5 P1-C：用量异常运行期 signal

#### 3.5.1 识别规则

| signal_kind | 触发条件 | priority |
|---|---|---|
| usage_spike | 单次调用 input_tokens + output_tokens > 100000 | 70 |
| low_cache_hit_rate | input_tokens > 10000 且 cache_hit_rate < 10% | 65 |
| unknown_usage_dominant | 窗口 1 小时内 activity_tag=unknown 占比 > 50% | 60 |

#### 3.5.2 签名维度

```
usage_spike:agent:workspace:conversation
low_cache_hit_rate:agent:workspace:conversation
unknown_usage_dominant:agent:workspace
```

---

### 3.6 P2-A：关键文件可配置化

#### 3.6.1 方案

- 移除 [helpers.py:13-19](file:///d:/workspace/agentic_factory/apps/agent-observer/backend/app/behavior_signals/helpers.py#L13-L19) 硬编码的 KEY_PATH_PATTERNS
- 引入项目级配置文件：`key_file_patterns.json`（每个被观测项目根目录）
- 默认模式（通用，适用于任何项目）：

| 模式 | 说明 |
|---|---|
| `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `pom.xml` | 项目根配置 |
| `*.lock` / `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` / `poetry.lock` / `Cargo.lock` | 锁文件 |
| `main.py` / `main.ts` / `main.js` / `app.py` / `index.ts` / `index.js` / `index.go` | 入口文件 |
| `.github/workflows/*.yml` / `.gitlab-ci.yml` / `Jenkinsfile` / `.circleci/config.yml` | CI 配置 |
| `.env` / `.env.local` / `.env.production` | 环境变量文件 |

- 支持项目自定义覆盖：在项目根放 `key_file_patterns.json` 可覆盖默认模式

#### 3.6.2 priority

- 保持 85

---

### 3.7 P2-B：决策回流

#### 3.7.1 conclusion_code 扩档

新增两档：

| conclusion_code | 含义 | 适用场景 |
|---|---|---|
| expected_nonzero_exit | 预期非零退出 | 业务门禁、校验失败等按设计返回非零的情况 |
| duplicate_signal | 重复信号 | 同类问题已处理过，无需再次关注 |

#### 3.7.2 降权机制

- 同签名 signal 被标记为 `expected_nonzero_exit` 或 `accepted_risk` 累计 >= 3 次后
- 该签名新 fact 生成的 signal priority 降至 30
- 在 signal 详情展示"已基于历史决策降权"

#### 3.7.3 needs_review 触发扩展

当前只看 snapshot_hash 变化，新增触发条件：
- occurrence_count 增长 >= 50%（如从 4 次涨到 6 次以上）
- 时间窗口内累积（如 1 小时内同签名出现 >= 5 次）

## 4. 验收标准

### 4.1 P0 验收

**敏感内容**：
- 对包含真实 OpenAI key / GitHub token / Azure SAS / HuggingFace token / PEM 私钥 / JWT / 银行卡号 / 身份证号 / 手机号的测试数据，100% 识别
- 对包含 "token" / "auth" / "secret" / "key" / "password" 关键字但无真实值的测试数据，0% 误报
- 对 `OPENAI_API_KEY=` 后为空或占位符的情况，0% 误报
- 对随机 16-19 位数字串（非银行卡号，Luhn 校验不通过），0% 误报
- 对随机 18 位数字串（非身份证号，校验位不匹配），0% 误报
- 对 11 位数字但不匹配运营商号段的字符串，0% 误报
- 对环境变量引用 `${OPENAI_API_KEY}` / `$GITHUB_TOKEN`，0% 误报
- 工具输出（function_call_output.output）中的敏感内容能被识别
- Agent 响应内容（agent_response.content）中的敏感内容能被识别
- Agent 推理（agent_reasoning.content）中的敏感内容能被识别
- 命令访问 `/etc/shadow` / `~/.ssh/id_rsa` / `C:\Windows\System32\config\SAM` 等敏感路径时，识别为 sensitive_path_access

**工具失败拆分**：
- prd-kit `check-status` 返回 `{"ok":false,"blocked":true}` 时，归类为 workflow_gate_blocked，priority=30
- Python traceback 归类为 tool_execution_failure，priority=95
- pytest 失败归类为 validation_failure，priority=60
- 不同 blocker 的 workflow_gate_blocked 不聚合成同一 signal

### 4.2 P1 验收

- 同命令 3 次失败生成 repeated_tool_failure signal，priority=80
- 会话 10 分钟无 content 但有工具调用生成 agent_loop_stuck signal，priority=75
- 单次调用 100k+ token 生成 usage_spike signal，priority=70

### 4.3 P2 验收

- 移除硬编码后，默认模式能识别通用项目结构的关键文件
- 项目配置 key_file_patterns.json 后，能正确识别该项目关键文件
- 同签名 3 次标记 expected_nonzero_exit 后，新 fact priority 降至 30
- needs_review 在 occurrence_count 增长 50% 时触发

## 5. 非目标

- **不涉及** agent-observer 自身健康观测（采集器掉线 / 处理任务失败 / 补证失败的聚合 signal），单独讨论
- **不涉及** "越界修改"识别（任务边界是项目特定的，需单独讨论）
- **不涉及** 补证能力扩展（破坏性操作 / 敏感内容的补证）
- **不涉及** 前端展示调整（标签 / 字段显示 / SignalCard 布局）
- **不涉及** 历史数据回溯重算

## 6. 实施顺序

```
P0（止血，识别失效修复）
  ├─ P0-A 敏感内容识别修正
  └─ P0-B 工具失败子类型拆分
      ↓
P1（核心价值补全）
  ├─ P1-A Agent 重复犯错识别
  ├─ P1-B Agent 卡循环识别
  └─ P1-C 用量异常运行期 signal
      ↓
P2（机制失效修复）
  ├─ P2-A 关键文件可配置化
  └─ P2-B 决策回流
```

每个 P 级别内可并行。P0 必须先完成，因为 P1-A 依赖工具失败拆分（业务门禁不触发重复犯错）。

## 7. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 敏感内容正则遗漏新格式 | 漏报 | 正则可配置，支持后续扩展 |
| 工具失败 JSON 解析性能 | 采集变慢 | 限制解析前 2000 字符，编译正则缓存 |
| 关键文件默认模式不全 | 漏报 | 支持项目自定义覆盖 |
| 决策降权误判 | 真问题被降权 | 阈值 >=3 次，且用户可手动恢复 |
