"""纯校验函数：银行卡 Luhn、中国身份证 ISO 7064 MOD 11-2。"""
from __future__ import annotations

from datetime import date


# 中国行政区划省份码（前两位）：11-65 为主流派码，71/81/82/83 为港澳台居民居住证。
_VALID_PROVINCE_CODES = frozenset(
    {11, 12, 13, 14, 15, 21, 22, 23, 31, 32, 33, 34, 35, 36, 37,
     41, 42, 43, 44, 45, 46, 50, 51, 52, 53, 54, 61, 62, 63, 64, 65,
     71, 81, 82, 83}
)


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


def _is_valid_region_code(code: str) -> bool:
    """检查前 6 位是否为有效行政区划代码（省份码白名单）。"""
    if len(code) != 6 or not code.isdigit():
        return False
    return int(code[:2]) in _VALID_PROVINCE_CODES


def _is_valid_date(year_str: str, month_str: str, day_str: str) -> bool:
    """检查日期是否有效（年份 1900-当前年份，月份 1-12，日期按月校验含闰年）。"""
    try:
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
    except ValueError:
        return False
    if year < 1900 or year > date.today().year:
        return False
    if month < 1 or month > 12:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def iso7064_mod11_2_check(value: str) -> bool:
    """中国居民身份证 18 位校验码（ISO 7064 MOD 11-2）+ 区域码 + 日期校验。

    仅校验校验位会导致约 1/11 的 18 位数字误中（如 URL 文章 ID）。
    增加区域码（省份码白名单）和出生日期校验可有效过滤非身份证数字串。
    """
    if len(value) != 18 or not value[:17].isdigit():
        return False
    if not _is_valid_region_code(value[:6]):
        return False
    if not _is_valid_date(value[6:10], value[10:12], value[12:14]):
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_chars = "10X98765432"
    total = sum(int(value[i]) * weights[i] for i in range(17))
    return check_chars[total % 11] == value[17].upper()
