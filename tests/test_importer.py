import pytest
from fund_analyzer.importer import (
    FundInfo, search_fund, infer_asset_class, infer_tracking,
    parse_code_amount_line, parse_batch_text,
)


def test_infer_asset_class_nasdaq():
    assert infer_asset_class("广发纳斯达克100指数(QDII)") == "us_equity"


def test_infer_asset_class_sp500():
    assert infer_asset_class("博时标普500ETF联接") == "us_equity"


def test_infer_asset_class_cn():
    assert infer_asset_class("易方达沪深300ETF联接") == "cn_equity"


def test_infer_asset_class_bond():
    assert infer_asset_class("招商中证全债指数") == "bond"


def test_infer_asset_class_unknown():
    assert infer_asset_class("某个奇怪名字") == "other"


def test_infer_tracking_nasdaq():
    t = infer_tracking("广发纳斯达克100指数(QDII)")
    assert t["index"] == "^NDX"
    assert t["lag_days"] == 2


def test_infer_tracking_sp500():
    t = infer_tracking("博时标普500ETF联接(QDII)")
    assert t["index"] == "^GSPC"


def test_infer_tracking_none():
    t = infer_tracking("某个奇怪基金")
    assert t == {}


def test_parse_code_amount_line():
    assert parse_code_amount_line("270042 50000") == ("270042", 50000.0, 0.0)
    assert parse_code_amount_line("270042  50000.5") == ("270042", 50000.5, 0.0)
    assert parse_code_amount_line("270042\t30000") == ("270042", 30000.0, 0.0)
    assert parse_code_amount_line("270042 50000 100") == ("270042", 50000.0, 100.0)


def test_parse_code_amount_line_invalid():
    assert parse_code_amount_line("invalid") is None
    assert parse_code_amount_line("") is None
    assert parse_code_amount_line("12345 100") is None  # not 6 digits


def test_parse_batch_text():
    text = "270042 50000\n050025 30000\n110020 20000"
    result = parse_batch_text(text)
    assert len(result) == 3
    assert result[1] == ("050025", 30000.0, 0.0)


def test_parse_batch_text_with_dca():
    text = "270042 50000 100\n050025 30000 50"
    result = parse_batch_text(text)
    assert len(result) == 2
    assert result[0] == ("270042", 50000.0, 100.0)


def test_parse_batch_text_with_blanks():
    text = "270042 50000\n\n050025 30000\n"
    result = parse_batch_text(text)
    assert len(result) == 2


def test_search_fund_integration():
    """Actual API call — needs network."""
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    http = HttpClient(ttl_minutes=30)
    em = EastMoney(http)
    info = search_fund("270042", em)
    if info:
        assert "广发" in info.name or "纳斯达克" in info.name
        assert info.asset_class == "us_equity"
