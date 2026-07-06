"""敏感识别规则表 + 占位值排除清单。

按类别分段：身份 / 支付 / 凭据密钥 / 敏感路径。规则是"正则 + 可选校验器 + 类别"
的数据表（不做类层次——纯正则规则用表结构最合适，模仿 Presidio 的 recognizer 类
只会徒增样板）。
"""
from __future__ import annotations

import re
from typing import Any, Callable

from app.sensitive.validators import iso7064_mod11_2_check, luhn_check

# hex-aware 边界：前后既不是十进制数字也不是 hex 字母，避免命中 trace ID / commit
# hash / object ID 里的数字片段。
_NB = r"(?<![0-9a-fA-F])"
_NE = r"(?![0-9a-fA-F])"


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


# ---------------------------------------------------------------------------
# 规则注册表。对外 category 用 8 类（phone/email/id_card/bank_card/token/secret/
# cookie + sensitive_reference），下游展示/聚合零改动。
# ---------------------------------------------------------------------------
RULES: list[dict[str, Any]] = [
    # --- 身份 ---
    _rule("phone_number", rf"{_NB}(?:\+?86[-\s]?)?1[3-9]\d{{9}}{_NE}", "phone"),
    _rule(
        "email_address",
        # 左边界 + local-part 必须字母数字开头：挡住把前一个字符（JSON 转义换行 \n
        # 里的 n、git diff 的 +）吞进来。配合 engine 的 decode，行首装饰器
        # @pytest.x / @app.get 前面是真换行（无 local 字符）也不命中。
        # 不加 TLD 白名单（真实 TLD 1500+，白名单会漏检 .media/.law）；代价是 _foo@ 这类
        # 罕见邮箱会漏检，换取挡住 \n 的 n 前缀这一主要误报源。
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "email",
    ),
    _rule("china_id_card", rf"{_NB}\d{{17}}[\dXx]{_NE}", "id_card", validator=iso7064_mod11_2_check),
    _rule("passport_number", r"(?i)(?:passport|pass_no)\s*[:=]\s*[A-Za-z0-9]{5,12}", "id_card"),
    # --- 支付 ---
    _rule("credit_card_luhn", r"\b(?:4[0-9]{15}|5[1-5][0-9]{14}|3[47][0-9]{13})\b", "bank_card", validator=luhn_check),
    # 银联 62xx 不挂 Luhn（国内 19 位借记卡多不过 Luhn），标 reason=unionpay 避免降 recall。
    _rule("unionpay_card", rf"{_NB}62\d{{14,17}}{_NE}", "bank_card", reason="unionpay"),
    _rule("bank_account", r"(?i)bank[_\-]?account\s*[:=]\s*\d{8,17}", "bank_card"),
    # swift_code 已移除：SWIFT/BIC 是公开银行路由码（如 URFKYK85X），非敏感。
    # --- 凭据 / 密钥 ---
    _rule("authorization", r"Authorization\s*:\s*(Bearer|Basic|token)\s+([A-Za-z0-9._~+/=-]{16,})", "token", match_type="authorization"),
    _rule("token_assignment", r"(?i)\b(?:access_token|api_key|api_token|openai_api_key|refresh_token|session_token|token)\b[\"'\s]*[:=][\"'\s]*([A-Za-z0-9._~+/=-]{16,})", "token"),
    _rule("secret_assignment", r"(?i)\b(?:client_secret|secret|password|credential)\b[\"'\s]*[:=][\"'\s]*([A-Za-z0-9._~+/=-]{8,})", "secret"),
    _rule("cookie_assignment", r"(?i)\b(?:Set-Cookie|Cookie)\s*:\s*([^=;\s]{2,})=([^;\s]{8,})", "cookie"),
    # openai_api_key 收紧：sk- 后要求连续字母数字（允许 proj- 前缀），不再吞
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
    # --- 敏感路径 ---
    _rule("linux_sensitive", r"(?:^|/)(?:etc/(?:shadow|passwd|sudoers)|root/.ssh/authorized_keys)", "sensitive_reference"),
    _rule("windows_sensitive", r"(?:^|[\\/])(?:Windows|WINDOWS)[\\/](?:System32|syswow64)[\\/]config[\\/](?:SAM|SECURITY|SYSTEM)", "sensitive_reference"),
    _rule("macos_sensitive", r"(?:^|/)Library/(?:Keychains|Security)/", "sensitive_reference"),
    _rule("env_file", r"(?:^|[\\/])\.(?:env|environment)(?:\.local)?(?:\.[a-z]+)?$", "sensitive_reference"),
    _rule("credential_file", r"(?:^|[\\/])(?:\.?credentials|\.?netrc|\.?htpasswd|\.?npmrc|\.?pypirc)(?:\.[a-z]+)?$", "sensitive_reference"),
    _rule("ssh_directory", r"(?:^|/)\.ssh/[a-z]+", "sensitive_reference"),
]

# 排除只对 matched_value 做（不对整条 raw_content），避免 "test" 子串让约 20% fact
# 整体失明。命中排除 → confidence 降为 low → detect_for_fact 只取 high，故不写库。
EXCLUSION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(?:x+)$", re.IGNORECASE),  # xxx...xxx 纯占位
    re.compile(r"^\$\{[A-Z_]+\}$"),  # ${ENV_VAR}
    re.compile(r"^\$[A-Z_]+$"),  # $ENV_VAR
    re.compile(r"<[^>]*?-?key[^>]*?>", re.IGNORECASE),  # <your-api-key>
    re.compile(r"(?:placeholder|sample|dummy)", re.IGNORECASE),
    re.compile(r"@(?:[a-z0-9.-]+\.)?example\.(?:com|org|net|edu|gov|cn|invalid|test|local)$", re.IGNORECASE),  # RFC 2606 占位域（含子域）
    # 已知测试/占位值（国标测试号、公开测试卡、占位字母串、占位赋值、空值/代码）—— 命中即降级 low
    re.compile(r"^13800138000$"),   # 中国移动标准测试号
    re.compile(r"^13900139000$"),   # 标准测试号
    re.compile(r"^13812345678$"),   # 顺序测试号
    re.compile(r"^11010519491231002X$", re.IGNORECASE),  # 国标测试身份证号
    re.compile(r"^6222020202020202\d{0,3}$"),  # 银联公开测试卡（16/19 位变体）
    re.compile(r"^4(?:532015112830366|111111111111111)$"),  # Visa 公开测试卡
    re.compile(r"^5500000000000004$"),     # Mastercard 公开测试卡
    re.compile(r"abcdefghijklmnop"),       # 占位字母序列（如 Bearer abcdefghijklmnop）
    re.compile(r"password\s*=\s*password$", re.IGNORECASE),  # 占位 password=password
    re.compile(r"\b(?:undefined|null|none|nil|getenv|getToken|getString)\b", re.IGNORECASE),  # 空值/代码
    re.compile(r"(?:Utils|Helper|Manager|Factory)\.[A-Za-z_]\w*\s*\("),  # 代码方法调用（JwtTokenUtils.getToken()）
    re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\s*\([^)]*\)$"),  # 形如 obj.method(...) 的代码调用
]
