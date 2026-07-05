"""Unified sensitive detector 单测 —— 覆盖对抗 review 修复点 [F9]-[F13]+[F6]。"""
from __future__ import annotations

import pytest

from app import sensitive_detector as det


def _cats(matches):
    return sorted({m["category"] for m in matches})


# ---------------------------------------------------------------------------
# 手机号 / hex 边界 [F9]
# ---------------------------------------------------------------------------

def test_detect_finds_phone():
    matches = det.detect("联系我 13521661669 谢谢")
    phones = [m for m in matches if m["category"] == "phone"]
    assert len(phones) == 1
    assert phones[0]["matched_value"] == "13521661669"
    assert phones[0]["confidence"] == "high"


def test_detect_phone_with_country_code():
    assert any(m["matched_value"].endswith("13521661669") for m in det.detect("+86-13521661669"))
    assert any(m["category"] == "phone" for m in det.detect("8613521661669"))


def test_detect_hex_boundary_blocks_trace_id_fragment():
    # [F9] 17250819195 是 hex trace ID 的数字片段，前后是 hex 字母，必须不命中。
    text = '"id": "rs_0065e2b7ea1be5ec016a44b6f17250819195a4a43a1d05258c"'
    phones = [m for m in det.detect(text) if m["category"] == "phone"]
    assert phones == [], f"hex 片段被误报为手机号: {phones}"


def test_detect_multiple_phones_finditer():
    # finditer 多命中，不是 search 单命中。
    text = "张三 13800138000 李四 13900139000 王五 13700137000"
    phones = [m for m in det.detect(text) if m["category"] == "phone"]
    assert len(phones) == 3


# ---------------------------------------------------------------------------
# 校验 per-match [F11]
# ---------------------------------------------------------------------------

def test_detect_id_card_iso_validates():
    # 110101199003076536 通过 ISO 7064 MOD 11-2（sum=226, 226%11=6, 校验位 '6'）。
    valid = det.detect("身份证号 110101199003076536")
    assert any(m["category"] == "id_card" and m["confidence"] == "high" for m in valid)
    # 校验位错误（末位 5）应被丢弃。
    invalid = det.detect("编号 110101199003076535")
    assert not any(m["category"] == "id_card" for m in invalid)


def test_detect_credit_card_luhn_validates():
    # 4111111111111111 是 Luhn 有效测试卡。
    assert any(m["category"] == "bank_card" for m in det.detect("卡号 4111111111111111"))
    # 末位错，不过 Luhn，丢弃。
    assert not any(m["category"] == "bank_card" and "4111111111111112" in m["matched_value"]
                   for m in det.detect("卡号 4111111111111112"))


def test_detect_iso_per_match_partial():
    # [F11] 同文本一真一假身份证：真证命中、假证丢弃，互不影响。
    text = "真 110101199003076536 假 110101199003076535"
    id_cards = [m for m in det.detect(text) if m["category"] == "id_card"]
    assert len(id_cards) == 1
    assert id_cards[0]["matched_value"] == "110101199003076536"


# ---------------------------------------------------------------------------
# 银联不挂 Luhn [F13]
# ---------------------------------------------------------------------------

def test_detect_unionpay_without_luhn():
    # 19 位银联借记卡号，不一定过 Luhn，但必须命中（不挂 Luhn）。
    matches = det.detect("银行卡 6222020200011000000")
    unionpay = [m for m in matches if m["reason_code"] == "unionpay"]
    assert len(unionpay) == 1
    assert unionpay[0]["category"] == "bank_card"
    assert unionpay[0]["confidence"] == "high"


# ---------------------------------------------------------------------------
# 排除语义 [F10]
# ---------------------------------------------------------------------------

def test_detect_exclusion_not_applied_to_full_text():
    # [F10] 原实现对整条文本做排除，"test" 子串会让手机号失明。修复后只对 matched_value 判排除。
    text = "running pytest test suite, call me at 13521661669"
    phones = [m for m in det.detect(text) if m["category"] == "phone"]
    assert len(phones) == 1
    assert phones[0]["confidence"] == "high"  # 不被 "test" 子串降级


def test_detect_exclusion_lows_placeholder_value():
    # matched_value 含 placeholder/sample/dummy 子串才标 low（example/test 已移除）。
    matches = det.detect("api_key=placeholdersecret1234567")
    api = [m for m in matches if m["category"] == "token"]
    assert api
    assert all(m["confidence"] == "low" for m in api)


def test_detect_email_example_domain_excluded():
    # example.{com|cn|local|test|invalid}（含子域）一律降级为 low（detect_for_fact
    # 只取 high，故不写库），避免 test@example.com 等占位邮箱把敏感信号撑成几百条噪音。
    for placeholder in (
        "mail alice@example.com",
        "send to pass@proxy.example.com",
        "bob@example.cn",
        "codex@example.local",
        "secret@example.test",
        "x@example.invalid",
    ):
        emails = [m for m in det.detect(placeholder) if m["category"] == "email"]
        assert emails and all(m["confidence"] == "low" for m in emails), placeholder


def test_detect_email_decorator_not_matched():
    # Python 装饰器 / 框架路由不能被当成邮箱（曾经的主要误报源）。
    assert det.detect("@pytest.mark.asyncio\ndef test_x(): pass") == []
    assert det.detect("@app.get('/health')") == []
    assert det.detect("@router.post('/items')") == []
    # JSON 转义换行 \n 里的 n 不能被当成 local-part 起始。
    decoded = det.detect_for_fact(None, '{"output":"pat\\n15035344@qq.com\\n"}')
    emails = [m["matched_value"] for m in decoded if m["category"] == "email"]
    assert emails == ["15035344@qq.com"]


# ---------------------------------------------------------------------------
# 业务词不误报（test_usage_risk.py:452 fixture）
# ---------------------------------------------------------------------------

def test_detect_business_words_no_false_positive():
    assert det.detect('git commit -m "token telemetry contract"') == []
    assert det.detect("uv run oh auth status") == []
    assert det.detect("latest update for the contest") == []


# ---------------------------------------------------------------------------
# sensitivity.py 独有 4 项补入
# ---------------------------------------------------------------------------

def test_detect_email():
    assert any(m["category"] == "email" for m in det.detect("mail me at alice@example.com"))


def test_detect_authorization_bearer():
    matches = det.detect("Authorization: Bearer abcdefghijklmnop123456")
    auth = [m for m in matches if m["match_type"].startswith("authorization_")]
    assert auth
    assert auth[0]["match_type"] == "authorization_bearer"
    assert auth[0]["category"] == "token"


def test_detect_cookie():
    assert any(m["category"] == "cookie" for m in det.detect("Set-Cookie: session=abcdefghijklmnop"))


# ---------------------------------------------------------------------------
# 去重 [F12]
# ---------------------------------------------------------------------------

def test_detect_dedup_same_phone_once():
    # 同一手机号只出现一次文本，phone 命中不重复。
    phones = [m for m in det.detect("13521661669") if m["category"] == "phone"]
    assert len(phones) == 1


# ---------------------------------------------------------------------------
# object_type 优先级
# ---------------------------------------------------------------------------

def test_object_type_priority_phone_over_secret():
    matches = det.detect("api_key=sk-abcdefghijklmnop123456 call 13521661669")
    assert det.object_type_from_matches(matches) == "phone"


def test_object_type_credential_for_token():
    matches = det.detect("token=sk-abcdefghijklmnop1234567890")
    assert det.object_type_from_matches(matches) == "credential"


# ---------------------------------------------------------------------------
# detect_for_fact: 截断 + 只 high [F6]
# ---------------------------------------------------------------------------

def test_detect_for_fact_returns_only_high():
    # example 值标 low，不返回。
    matches = det.detect_for_fact('{"projection": "api_key=exampleapikey12345"}', None)
    assert all(m["confidence"] == "high" for m in matches)


def test_detect_for_fact_truncates_large_text():
    # 手机号放在 256KiB 之后，应被截断丢弃。
    padding = "0" * (det.SCAN_BYTE_CAP + 100)
    text = padding + " 13521661669"
    assert not any(m["category"] == "phone" for m in det.detect_for_fact(text, None))


def test_detect_swallows_exceptions(monkeypatch):
    # [F6] _detect_impl 抛异常时 detect 返回 []，不向调用方冒泡。
    def boom(_text, _source):
        raise RuntimeError("regex explosion")

    monkeypatch.setattr(det, "_detect_impl", boom)
    assert det.detect("anything") == []


# ---------------------------------------------------------------------------
# 兼容 shim
# ---------------------------------------------------------------------------

def test_sensitive_matches_from_text_compat():
    matches = det.sensitive_matches_from_text("call 13521661669", "message_scan")
    assert any(m["category"] == "phone" for m in matches)
    assert matches[0]["evidence_key"] == "message_scan"


def test_sensitive_categories_from_text_compat():
    assert "phone" in det.sensitive_categories_from_text("13521661669")


# ---------------------------------------------------------------------------
# 端到端关键：目标会话手机号
# ---------------------------------------------------------------------------

def test_target_session_phone_detected():
    # 用户报告的会话 ref:76d4e2c57baceb3d 的手机号必须命中。
    assert any(m["matched_value"] == "13521661669" and m["category"] == "phone"
               for m in det.detect("用户的手机号是 13521661669"))
