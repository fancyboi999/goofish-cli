"""search analyze 纯统计单测：价格解析、分位数、分档建议（不碰浏览器）。"""

from goofish_cli.commands.search.analyze import (
    advise,
    median,
    parse_price,
    price_band,
)


def test_parse_price_yuan_symbol():
    assert parse_price("¥199.00") == 199.0
    assert parse_price("￥200") == 200.0


def test_parse_price_plain_and_garbage():
    assert parse_price("199元") == 199.0
    assert parse_price("面议") is None
    assert parse_price(None) is None
    assert parse_price(True) is None


def test_percentile_median_band():
    vals = [100, 120, 150, 180, 200, 220, 260, 300]
    band = price_band(vals)
    assert band["count"] == 8
    assert band["min"] == 100 and band["max"] == 300
    assert band["p25"] == 150
    assert band["median"] == 190.0
    assert band["p75"] == 220
    assert median([]) is None


def test_small_sample_only_band_no_direction():
    advice = advise(160.0, [100, 120, 150], sample_size=3)
    assert advice["confidence"] == "low"
    assert "样本不足" in advice["suggestion"]


def test_above_p75_suggests_lower():
    advice = advise(300.0, [100, 120, 150, 180, 200, 220, 260, 300], sample_size=8)
    assert "高于市场" in advice["position"]
    assert "降至" in advice["suggestion"]


def test_in_band_reasonable():
    advice = advise(160.0, [100, 120, 150, 180, 200, 220, 260, 300], sample_size=8)
    assert "合理区间" in advice["position"]


def test_below_p25_suggests_raise():
    advice = advise(80.0, [100, 120, 150, 180, 200, 220, 260, 300], sample_size=8)
    assert "偏低" in advice["position"]
    assert "上调" in advice["suggestion"]


def test_no_price_only_band():
    advice = advise(None, [100, 120, 150, 180, 200, 220, 260, 300], sample_size=8)
    assert "P25" in advice["suggestion"]
