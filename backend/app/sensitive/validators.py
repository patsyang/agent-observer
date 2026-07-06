"""纯校验函数：银行卡 Luhn、中国身份证 ISO 7064 MOD 11-2。"""
from __future__ import annotations


def luhn_check(number: str) -> bool:
    """银行卡号 Luhn 校验。长度 13-19。"""
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


def iso7064_mod11_2_check(value: str) -> bool:
    """中国居民身份证 18 位校验码（ISO 7064 MOD 11-2）。"""
    if len(value) != 18 or not value[:17].isdigit():
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_chars = "10X98765432"
    total = sum(int(value[i]) * weights[i] for i in range(17))
    return check_chars[total % 11] == value[17].upper()
