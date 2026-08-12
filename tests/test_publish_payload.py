"""验证 _build_publish_data 的 payload 构造 —— 关键字段防回归。"""

import importlib
from contextlib import contextmanager
from unittest.mock import patch

from goofish_cli.commands.item.publish import _build_publish_data

publish_module = importlib.import_module("goofish_cli.commands.item.publish")

CAT = {
    "cat_id": "50106003",
    "cat_name": "男士毛呢大衣",
    "channel_cat_id": "126860482",
    "tb_cat_id": "50025883",
    "root_channel_cat_id": "126866981",
    "level2_channel_cat_id": "127292002",
    "level3_channel_cat_id": "127300001",
}
LOC = {
    "division_id": "110105",
    "all": [{
        "area": "朝阳区", "city": "北京", "divisionId": 110105,
        "longitude": "116.4", "latitude": "39.9",
        "poi": "世纪村三区", "poiId": "B000A7IKQQ", "prov": "北京",
    }],
}
IMGS = [{"url": "https://cdn/x.png", "width": 1024, "height": 1024}]


def _build(**overrides):
    kwargs = dict(
        title="真标题",
        desc="真描述。第二句。",
        image_infos=IMGS,
        price=1999.0,
        original_price=None,
        delivery="包邮",
        post_price=0,
        can_self_pickup=True,
        cat_info=CAT,
        location=LOC,
    )
    kwargs.update(overrides)
    return _build_publish_data(**kwargs)


def test_title_desc_separate_must_be_true():
    """防回归：titleDescSeparate 必须 True，否则服务端会按句号拆 desc、丢弃 title。
    验证来自真实发布 itemId=1045171414271 的返回：设 False 时 title 被忽略。
    """
    data = _build()
    assert data["itemTextDTO"]["titleDescSeparate"] is True
    assert data["itemTextDTO"]["title"] == "真标题"
    assert data["itemTextDTO"]["desc"] == "真描述。第二句。"


def test_price_converted_to_cent():
    data = _build(price=1999.0)
    assert data["itemPriceDTO"]["priceInCent"] == "199900"


def test_delivery_baoyou_flags():
    data = _build(delivery="包邮")
    fee = data["itemPostFeeDTO"]
    assert fee["canFreeShipping"] is True
    assert fee["supportFreight"] is True


def test_cat_info_mapped():
    data = _build()
    cat = data["itemCatDTO"]
    assert cat["catId"] == "50106003"
    assert cat["channelCatId"] == "126860482"
    assert cat["tbCatId"] == "50025883"
    assert cat["rootChannelCatId"] == "126866981"
    assert cat["level2ChannelCatId"] == "127292002"
    assert cat["level3ChannelCatId"] == "127300001"


def test_location_mapped():
    data = _build()
    addr = data["itemAddrDTO"]
    assert addr["divisionId"] == 110105
    assert addr["prov"] == "北京"
    assert addr["city"] == "北京"
    assert addr["gps"] == "116.4,39.9"


@contextmanager
def _passthrough_context():
    yield


def test_multi_image_publish_consumes_one_write_token():
    acquired: list[str] = []

    @contextmanager
    def fake_acquire(bucket: str):
        acquired.append(bucket)
        yield

    uploads = [
        {"url": f"https://cdn/{index}.png", "width": 100, "height": 100}
        for index in range(3)
    ]
    with (
        patch.object(publish_module, "acquire", fake_acquire),
        patch.object(publish_module, "watch", _passthrough_context),
        patch.object(publish_module.Session, "load", return_value=object()),
        patch.object(publish_module, "upload", side_effect=uploads),
        patch.object(publish_module, "recommend", return_value=CAT),
        patch.object(publish_module, "get_default_location", return_value={}),
        patch.object(
            publish_module,
            "call",
            return_value={"ret": ["SUCCESS::调用成功"], "data": {"itemId": "123"}},
        ),
    ):
        result = publish_module.publish(
            title="示例标题",
            desc="示例描述",
            images=["1.png", "2.png", "3.png"],
            price=199,
        )

    assert acquired == ["item.write"]
    assert result["ok"] is True
    assert result["item_id"] == "123"
