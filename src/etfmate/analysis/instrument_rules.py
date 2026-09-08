"""Verified secondary-market ETF resale rules, separate from broker freezes.

T0/T1 here describes whether an exchange purchase may be resold that day. It
does not describe cash withdrawal, primary-market creation/redemption or an
account's currently unfrozen sellable quantity. Unknown instruments stay unknown.
Sources and the verification boundary are documented in trading-eligibility.md.
"""
from __future__ import annotations

from typing import Any


VERIFIED_ON = "2026-09-08"
RULES_EFFECTIVE_ON = "2026-07-06"
SSE_RULES = "https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml"
SZSE_RULES = "https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf"

# Explicit scope: neither a numeric code prefix nor the word ETF proves T+0.
_DOMESTIC_EQUITY = {
    "159141": "科创创业人工智能ETF永赢",
    "159259": "成长ETF易方达",
    "159263": "价值ETF易方达",
    "159326": "电网设备ETF华夏",
    "159566": "储能电池ETF易方达",
    "159781": "科创创业ETF易方达",
    "159870": "化工ETF鹏华",
    "510500": "中证500ETF南方",
    "515880": "通信ETF国泰",
    "560280": "工程机械ETF广发",
    "562800": "稀有金属ETF嘉实",
    "588160": "科创新材料ETF南方",
}
_PRODUCT_SOURCES = {
    "159141": "https://static.cninfo.com.cn/finalpage/2025-11-25/1224823211.PDF",
    "159259": "https://www.efunds.com.cn/Mobile/fund/159259.shtml",
    "159263": "https://www.efunds.com.cn/Mobile/fund/159263.shtml",
    "159326": "https://accountquery.chinaamc.com/upload/resources/file/2026/03/23/62242c27b6d6474fa32326e8df0fca9c.pdf",
    "159566": "https://www.efunds.com.cn/Mobile/fund/159566.shtml",
    "159781": "https://www.efunds.com.cn/Mobile/fund/159781.shtml",
    "159870": "https://static.cninfo.com.cn/finalpage/2026-04-03/1225077038.PDF",
    "510500": "https://www.nffund.com/main/files/2024/03/29/234344061328.pdf",
    "515880": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2024-06-13/515880_20240613_NG2X.pdf",
    "560280": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-06-10/560280_20250610_I9QI.pdf",
    "562800": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-03-12/562800_20260312_WXTQ.pdf",
    "588160": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-08-31/588160_20230831_CCSJ.pdf",
}
_SAME_DAY_RESALE = {
    "159687": ("亚太精选ETF南方", "CROSS_BORDER_ETF", "2022-12-27",
               "https://www.szse.cn/www/disclosure/notice/fund/t20221227_598005.html"),
    "513120": ("港股创新药ETF广发", "CROSS_BORDER_ETF", "2022-07-12",
               "https://www.sse.com.cn/disclosure/announcement/listing/c/c_20220711_5705364.shtml"),
    "518880": ("黄金ETF华安", "GOLD_ETF", "2013-07-29",
               "https://wap.huaan.com.cn/news/2013-07-29/175178_1.shtml"),
}


def get_instrument_rule(code: str) -> dict[str, Any]:
    """Return independently verified resale regime; never infer account inventory."""
    normalized = str(code).strip().lower()
    if normalized.startswith(("sh", "sz")):
        normalized = normalized[2:]
    normalized = normalized.split(".", 1)[0]
    if normalized not in _DOMESTIC_EQUITY and normalized not in _SAME_DAY_RESALE:
        return {
            "code": normalized, "name": normalized, "settlement": "UNKNOWN",
            "same_day_sell_allowed": None, "exchange": None,
            "instrument_category": "UNKNOWN", "source_urls": [],
            "verified_on": None, "rules_effective_on": None,
            "note": "当前研究范围外或交易制度未核验，不能按代码前缀推断T+0/T+1。",
        }
    exchange = "SZSE" if normalized.startswith("159") else "SSE"
    general_rule = SZSE_RULES if exchange == "SZSE" else SSE_RULES
    same_day = normalized in _SAME_DAY_RESALE
    if same_day:
        name, category, source_date, specific_source = _SAME_DAY_RESALE[normalized]
        source_urls = [specific_source, general_rule]
    else:
        name, category, source_date = _DOMESTIC_EQUITY[normalized], "DOMESTIC_EQUITY_ETF", "2026-04-24"
        source_urls = [general_rule, _PRODUCT_SOURCES[normalized]]
    return {
        "code": normalized, "name": name, "exchange": exchange,
        "settlement": "T0" if same_day else "T1",
        "same_day_sell_allowed": same_day, "instrument_category": category,
        "source_urls": source_urls, "source_published_on": source_date,
        "verified_on": VERIFIED_ON, "rules_effective_on": RULES_EFFECTIVE_ON,
        "note": "仅说明二级市场买入份额的回转交易制度；平台冻结、在途卖单和实际可卖量另行计算。",
    }
