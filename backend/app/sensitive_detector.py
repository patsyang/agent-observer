"""Unified sensitive-content detector — the single source of truth.

融合 ``behavior_signals/sensitivity_rules.py``（25 种 + Luhn / ISO 7064 / 排除）
与 ``sensitivity.py`` 独有 4 项（Authorization 头 / Cookie / email / 银联 62xx）。
ingest 阶段 per-fact 调用一次，命中即写 ``risk_signals``（object_type 派生索引）
与 ``evidence_projections.projection_json``（sensitive_matches 详情）。

这是全系统唯一的敏感检测点。展示层、聚合层、会话命中成员资格全部读 detector
持久化的结果，不再各自重扫文本。

对抗 review 修复（见 plan [F9]-[F13]）：
- [F9] phone / id_card / bank / credit 边界升级为 hex-aware，挡住 hex trace ID /
      commit hash 里的数字片段（真实 FP ``17250819195`` 来自 hex 串片段）。
- [F10] 排除只对 matched_value 做（不对整条 raw_content）、用词边界、移除 ``test``
      关键词——否则 "testing"/"latest" 会让约 20% fact 整体失明。
- [F11] finditer + per-match 校验：Luhn / ISO 校验失败只丢弃该 match，不影响同
      规则的其它 match。
- [F12] 输出按 (start, end, category) 去重，避免 generic_api_key 与 token_assignment
      同 span 重复命中。
- [F13] 银联 62xx 不挂 Luhn（国内 19 位借记卡多不过 Luhn），标 reason=unionpay，
      避免降 recall。
- [F6]  detect 内部吞异常、调用方截断 raw_content，单条 fact 失败不波及 ingest 事务。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

# hex-aware 边界：前后既不是十进制数字也不是 hex 字母，避免命中 trace ID / commit
# hash / object ID 里的数字片段。
_NB = r"(?<![0-9a-fA-F])"
_NE = r"(?![0-9a-fA-F])"

# 检测后对 fact 文本的总长度上限，防止超大 raw_content 拖垮 ingest 热路径。
SCAN_BYTE_CAP = 262144  # 256 KiB


def _rule(
    name: str,
    pattern: str,
    category: str,
    *,
    match_type: str | None = None,
    validator: Callable[[str], bool] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "pattern": re.compile(pattern),
        "category": category,
        "match_type": match_type or name,
        "validator": validator,
        "reason": reason or name,
    }


def _luhn_check(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    for i, d in enumerate(digits[::-1]):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _iso7064_mod11_2_check(value: str) -> bool:
    if len(value) != 18 or not value[:17].isdigit():
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_chars = "10X98765432"
    total = sum(int(value[i]) * weights[i] for i in range(17))
    return check_chars[total % 11] == value[17].upper()


# ---------------------------------------------------------------------------
# 规则注册表：sensitivity_rules.py 25 种为骨干 + sensitivity.py 独有 4 项
# 对外 category 用 legacy 8 类（phone/email/id_card/bank_card/token/secret/cookie
# + sensitive_reference），下游展示/聚合零改动。
# ---------------------------------------------------------------------------

RULES: list[dict[str, Any]] = [
    # --- Identity ---
    _rule("phone_number", rf"{_NB}(?:\+?86[-\s]?)?1[3-9]\d{{9}}{_NE}", "phone"),
    _rule(
        "email_address",
        # 左边界 + local-part 必须以字母数字开头：挡住把前一个字符（尤其 JSON 转义
        # 换行 \n 里的 n、git diff 的 +）吞进来的误判。配合 detect_for_fact 的解码，
        # 行首装饰器 @pytest.x / @app.get 前面是真换行（无 local 字符）也不会命中。
        # 不加 TLD 白名单：真实 TLD 有 1500+，白名单会静默漏检真实邮箱（如 .media/.law）；
        # decode + 左边界已足以消灭装饰器误报（实测残余为零）。
        # 注意：代价是 local-part 以 _ / . 开头的罕见邮箱（如 _foo@x.com）会被漏检，
        # 换取挡住 \n 的 n 前缀这一主要误报源。
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "email",
    ),
    _rule("china_id_card", rf"{_NB}\d{{17}}[\dXx]{_NE}", "id_card", validator=_iso7064_mod11_2_check),
    _rule("passport_number", r"(?i)(?:passport|pass_no)\s*[:=]\s*[A-Za-z0-9]{5,12}", "id_card"),
    # --- Payment ---
    _rule("credit_card_luhn", r"\b(?:4[0-9]{15}|5[1-5][0-9]{14}|3[47][0-9]{13})\b", "bank_card", validator=_luhn_check),
    _rule("unionpay_card", rf"{_NB}62\d{{14,17}}{_NE}", "bank_card", reason="unionpay"),  # [F13] 不挂 Luhn
    _rule("bank_account", r"(?i)bank[_\-]?account\s*[:=]\s*\d{8,17}", "bank_card"),
    # swift_code 移除：SWIFT/BIC 是公开银行路由码（如 URFKYK85X），非敏感，归类 bank_card 是误报。
    # --- Credentials / tokens (sensitivity.py 独有 + sensitivity_rules) ---
    _rule("authorization", r"Authorization\s*:\s*(Bearer|Basic|token)\s+([A-Za-z0-9._~+/=-]{16,})", "token", match_type="authorization"),
    _rule("token_assignment", r"(?i)\b(?:access_token|api_key|api_token|openai_api_key|refresh_token|session_token|token)\b[\"'\s]*[:=][\"'\s]*([A-Za-z0-9._~+/=-]{16,})", "token"),
    _rule("secret_assignment", r"(?i)\b(?:client_secret|secret|password|credential)\b[\"'\s]*[:=][\"'\s]*([A-Za-z0-9._~+/=-]{8,})", "secret"),
    _rule("cookie_assignment", r"(?i)\b(?:Set-Cookie|Cookie)\s*:\s*([^=;\s]{2,})=([^;\s]{8,})", "cookie"),
    # openai_api_key 收紧：要求 sk- 后是连续字母数字（允许 proj- 前缀），不再吞
    # sk-result-... / sk-monitoring-... 这类带连字符的内部 ID（曾单条命中 2398 次）。
    _rule("openai_api_key", r"sk-(?:proj-)?[A-Za-z0-9]{40,}", "token"),
    _rule("github_token", r"gh[pousr]_[A-Za-z0-9_]{30,}", "token"),
    _rule("azure_sas_token", r"SharedAccessSignature=[a-zA-Z0-9+%/=]+", "token"),
    _rule("huggingface_token", r"hf_[A-Za-z0-9]{34,}", "token"),
    _rule("generic_api_key", r"(?i)(?:api[_\-]?key|apikey)\s*[:=]\s*[A-Za-z0-9]{16,}", "token"),
    _rule("jwt_token", r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "token"),
    _rule("aws_secret_key", r"(?i)aws[_\-]?secret[_\-]?access?[_\-]?key\s*[:=]\s*[A-Za-z0-9/+=]{40}", "secret"),
    _rule("pem_private_key", r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----", "secret"),
    _rule("ssh_private_key", r"-----BEGIN OPENSSH PRIVATE KEY-----", "secret"),
    _rule("database_password", r"(?i)(?:db[_\-]?pass(?:word)?|database[_\-]?password)\s*[:=]\s*\S{8,}", "secret"),
    _rule("smtp_password", r"(?i)smtp[_\-]?pass\s*[:=]\s*\S{8,}", "secret"),
    _rule("oauth_token", r"(?i)oauth[_\-]?token\s*[:=]\s*[A-Za-z0-9_-]{20,}", "token"),
    _rule("private_key_content", r"(?:private_key|secret)\s*[:=]\s*(?:[\"']?)[A-Za-z0-9+/=]{40,}", "secret"),
    # --- Sensitive paths ---
    _rule("linux_sensitive", r"(?:^|/)(?:etc/(?:shadow|passwd|sudoers)|root/.ssh/authorized_keys)", "sensitive_reference"),
    _rule("windows_sensitive", r"(?:^|[\\/])(?:Windows|WINDOWS)[\\/](?:System32|syswow64)[\\/]config[\\/](?:SAM|SECURITY|SYSTEM)", "sensitive_reference"),
    _rule("macos_sensitive", r"(?:^|/)Library/(?:Keychains|Security)/", "sensitive_reference"),
    _rule("env_file", r"(?:^|[\\/])\.(?:env|environment)(?:\.local)?(?:\.[a-z]+)?$", "sensitive_reference"),
    _rule("credential_file", r"(?:^|[\\/])(?:\.?credentials|\.?netrc|\.?htpasswd|\.?npmrc|\.?pypirc)(?:\.[a-z]+)?$", "sensitive_reference"),
    _rule("ssh_directory", r"(?:^|/)\.ssh/[a-z]+", "sensitive_reference"),
]

# [F10] 排除只对 matched_value 做（不对整条 raw_content），避免 "test" 子串让约 20%
# fact 整体失明。锚定 pattern（xxx / ${ENV} / $ENV / <your-key>）精确无误伤；关键词
# 子串匹配只保留 placeholder/sample/dummy —— 移除 example（会误伤 alice@example.com
# 这类 email 域名，而 detect_for_fact 只取 high 会导致真 email 漏报）和 test（失明）。
EXCLUSION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(?:x+)$", re.IGNORECASE),  # xxx...xxx 纯占位
    re.compile(r"^\$\{[A-Z_]+\}$"),  # ${ENV_VAR}
    re.compile(r"^\$[A-Z_]+$"),  # $ENV_VAR
    re.compile(r"<[^>]*?-?key[^>]*?>", re.IGNORECASE),  # <your-api-key>
    re.compile(r"(?:placeholder|sample|dummy)", re.IGNORECASE),
    re.compile(r"@(?:[a-z0-9.-]+\.)?example\.(?:com|org|net|edu|gov|cn|invalid|test|local)$", re.IGNORECASE),  # RFC 2606 占位域（含子域）
    # 已知测试/占位值（国标测试号、公开测试卡、占位字母串、占位赋值）—— 命中即降级为 low
    re.compile(r"^13800138000$"),   # 中国移动标准测试号
    re.compile(r"^13900139000$"),   # 标准测试号
    re.compile(r"^13812345678$"),   # 顺序测试号
    re.compile(r"^11010519491231002X$", re.IGNORECASE),  # 国标测试身份证号
    re.compile(r"^6222020202020202\d{0,3}$"),  # 银联公开测试卡（16/19 位变体）
    re.compile(r"^4(?:532015112830366|111111111111111)$"),  # Visa 公开测试卡
    re.compile(r"^5500000000000004$"),     # Mastercard 公开测试卡
    re.compile(r"abcdefghijklmnop"),       # 占位字母序列（如 Bearer abcdefghijklmnop）
    re.compile(r"password\s*=\s*password$", re.IGNORECASE),  # 占位 password=password
    re.compile(r"\b(?:undefined|null|none|nil|getenv|getToken|getString)\b", re.IGNORECASE),  # 空值/代码，非真实凭据
    re.compile(r"(?:Utils|Helper|Manager|Factory)\.[A-Za-z_]\w*\s*\("),  # 代码方法调用（JwtTokenUtils.getToken()）
    re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\s*\([^)]*\)$"),  # 形如 obj.method(...) 的代码调用
]


def _matches_exclusion(value: str) -> bool:
    return any(pat.search(value) for pat in EXCLUSION_PATTERNS)


def _preview(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= 48:
        return normalized
    return f"{normalized[:24]}...{normalized[-12:]}"


def _match_dict(rule: dict[str, Any], m: re.Match, confidence: str, source: str) -> dict[str, Any]:
    match_type = rule["match_type"]
    if rule["name"] == "authorization" and m.lastindex and m.lastindex >= 1:
        match_type = f"authorization_{m.group(1).lower()}"
    return {
        "category": rule["category"],
        "match_type": match_type,
        "confidence": confidence,
        "evidence_key": source,
        "matched_value": m.group(0)[:100],
        "matched_preview": _preview(m.group(0)),
        "reason_code": rule["reason"],
        "_span": (m.start(), m.end()),
    }


def _detect_impl(text: str, source: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()  # [F12] (start, end, category) 去重
    for rule in RULES:
        validator = rule["validator"]
        for m in rule["pattern"].finditer(text):  # finditer 多命中
            value = m.group(0)
            if validator is not None and not validator(value):  # [F11] per-match 校验，失败只丢该 match
                continue
            confidence = "low" if _matches_exclusion(value) else "high"  # [F10] 只对 matched_value 判排除
            key = (m.start(), m.end(), rule["category"])
            if key in seen:  # [F12] 去重
                continue
            seen.add(key)
            hits.append(_match_dict(rule, m, confidence, source))
    hits.sort(key=lambda h: h["_span"])
    for h in hits:
        h.pop("_span", None)
    return hits


def detect(text: str, *, source: str = "ingest") -> list[dict[str, Any]]:
    """对纯文本跑全部规则，返回 legacy 形状的 match dict 列表。

    finditer 多命中；Luhn/ISO 校验失败的单条 match 被丢弃；同 (span, category) 去重。
    任何异常都被吞掉返回空列表（[F6]，避免拖垮 ingest 事务）。
    """
    if not text:
        return []
    try:
        return _detect_impl(text, source)
    except Exception:
        return []


def detect_for_fact(projection_json_text: str, raw_content: str | None, *, source: str = "ingest") -> list[dict[str, Any]]:
    """ingest 专用：拼接 projection_json + raw_content，截断后扫描，只返回 high 命中。

    只取 high 命中是因为 risk_signal / projection.sensitive_matches 只持久化高可信
    命中；low（占位符/示例值）不写库。

    扫描前先用 ``_decode_for_scan`` 把 JSON 记录解码成可读文本（真换行）——
    raw_content 里换行被转义成字面 ``\\n``，直接扫会把 n 当成 email local-part
    起始（``\\n15035344@qq.com`` → ``n15035344@qq.com``），并让行首装饰器
    ``@pytest.mark.asyncio`` 被误判为邮箱。解码后换行变空白，两类误判同时消失。
    """
    text = "\n".join(p for p in (projection_json_text or "", raw_content or "") if p)
    if not text:
        return []
    text = _decode_for_scan(text)
    text = text[:SCAN_BYTE_CAP]
    return [m for m in detect(text, source=source) if m["confidence"] == "high"]


def _decode_for_scan(text: str) -> str:
    """把 JSON 记录串解码为可读文本，换行还原为真换行。

    优先 json.loads 后取所有标量值（字符串 + 数字，字段间真换行分隔）；失败
    （多条记录拼接等）时，仅在文本看起来像 JSON（以 {/[/" 开头）时才反转义，
    否则原样返回——避免把非 JSON 纯文本（如 Windows 路径 C:\\Users\\new）里的
    反斜杠序列误破坏。两条路径都保证 ``\\n`` 不再以"反斜杠+n"形式进入正则。
    """
    stripped = text.lstrip()
    looks_json = stripped[:1] in ('{', '[', '"')
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return _unescape_json_string(text) if looks_json else text
    parts: list[str] = []
    _collect_scalar_values(obj, parts)
    if parts:
        return "\n".join(parts)
    return _unescape_json_string(text) if looks_json else text


def _collect_scalar_values(obj: Any, out: list[str]) -> None:
    """递归收集字符串与数字值（数字也收，避免 {"phone": 13812345678} 漏检）。"""
    if isinstance(obj, str):
        if obj:
            out.append(obj)
    elif isinstance(obj, bool):  # bool 是 int 子类，先判；True/False 不当数字收
        return
    elif isinstance(obj, (int, float)):
        out.append(str(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_scalar_values(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _collect_scalar_values(value, out)


def _unescape_json_string(text: str) -> str:
    """逐字符反转义常见 JSON 字符串转义（\\n \\t \\r \\" \\/ \\\\）。仅在文本像 JSON 时调用。"""
    return (
        text.replace("\\\\", "\x00")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
        .replace('\\"', '"')
        .replace("\\/", "/")
        .replace("\x00", "\\")
    )


def object_type_from_matches(matches: list[dict[str, Any]]) -> str:
    """从命中列表算 risk_signals.object_type，优先级对齐 service.py 的旧实现。"""
    cats = {m["category"] for m in matches}
    if "phone" in cats:
        return "phone"
    if "email" in cats:
        return "email"
    if "id_card" in cats:
        return "id_card"
    if "bank_card" in cats:
        return "bank_card"
    if "token" in cats or "secret" in cats:
        return "credential"
    if "cookie" in cats:
        return "cookie"
    if "auth" in cats:
        return "auth"
    if cats:
        return sorted(cats)[0]
    return "sensitive_object"


# ---------------------------------------------------------------------------
# 兼容层：替代原 sensitivity.py 的对外函数名，让展示层 import 零改动。
# ---------------------------------------------------------------------------

def sensitive_matches_from_text(value: object, evidence_key: str = "text") -> list[dict[str, Any]]:
    return detect(str(value or ""), source=evidence_key)


def sensitive_categories_from_text(value: object) -> list[str]:
    return sorted({m["category"] for m in sensitive_matches_from_text(value)})
