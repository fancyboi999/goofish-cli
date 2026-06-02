"""纯函数测 item list 的参数校验 + 提取。"""
from goofish_cli.commands.item.list import __test__ as t

# ── _normalize_limit ──────────────────────────────────────


def test_normalize_limit_clamps_min():
    assert t["_normalize_limit"](0) == 1
    assert t["_normalize_limit"](-5) == 1


def test_normalize_limit_clamps_max():
    assert t["_normalize_limit"](200) == 100
    assert t["_normalize_limit"](9999) == 100


def test_normalize_limit_passes_valid():
    assert t["_normalize_limit"](50) == 50
    assert t["_normalize_limit"](1) == 1
    assert t["_normalize_limit"](100) == 100


def test_normalize_limit_non_int_defaults():
    assert t["_normalize_limit"]("abc") == 20
    assert t["_normalize_limit"](None) == 20
    assert t["_normalize_limit"]("") == 20


# ── _extract_item ──────────────────────────────────────────


def test_extract_item_full():
    card = {
        "id": "123456",
        "title": "测试商品",
        "priceInfo": {"preText": "¥", "price": "1999"},
        "itemStatus": 0,
        "picInfo": {"picUrl": "https://img.alicdn.com/test.jpg"},
        "itemLabelDataVO": {
            "labelData": {
                "r3": {
                    "tagList": [
                        {"data": {"content": "购入价1.8折"}},
                        {"data": {"content": "包邮"}},
                    ]
                }
            }
        },
    }
    result = t["_extract_item"](card)
    assert result["item_id"] == "123456"
    assert result["title"] == "测试商品"
    assert result["price"] == "¥1999"
    assert result["status"] == "在售"
    assert result["tags"] == ["购入价1.8折", "包邮"]


def test_extract_item_minimal():
    result = t["_extract_item"]({})
    assert result["item_id"] == ""
    assert result["price"] == ""
    assert result["tags"] == []


def test_extract_item_price_missing_pretext():
    card = {"id": "111", "priceInfo": {"price": "50"}}
    result = t["_extract_item"](card)
    assert result["price"] == "50"


def test_extract_item_status_offline():
    card = {"id": "222", "itemStatus": 1}
    result = t["_extract_item"](card)
    assert result["status"] == "已下架"


def test_extract_item_filters_img_label():
    # 真机复现：type=="img" 的标签 content 是图标 key（freeShippingIcon），
    # 不是给人看的文案，必须过滤；type=="text" 的保留。
    card = {
        "id": "333",
        "itemLabelDataVO": {
            "labelData": {
                "r3": {"tagList": [{"data": {"type": "text", "content": "2人想要"}}]},
                "r1": {
                    "tagList": [
                        {"data": {"type": "img", "content": "freeShippingIcon", "url": "http://x"}}
                    ]
                },
            }
        },
    }
    result = t["_extract_item"](card)
    assert result["tags"] == ["2人想要"]
