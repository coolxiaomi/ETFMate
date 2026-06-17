from etfmate.market.providers import market_prefix, normalize_etf_code


def test_normalize_etf_code():
    assert normalize_etf_code("510300") == "510300"
    assert normalize_etf_code("sh510300") == "510300"
    assert normalize_etf_code("510300.SH") == "510300"


def test_market_prefix():
    assert market_prefix("510300") == "sh"
    assert market_prefix("159915") == "sz"
