"""验证 _build_publish_data 的 payload 构造 —— 关键字段防回归。"""

from goofish_cli.commands.item.publish import _build_publish_data

CAT = {"cat_id": "50106003", "cat_name": "男士毛呢大衣", "channel_cat_id": "126860482", "tb_cat_id": "50025883"}
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


def test_location_mapped():
    data = _build()
    addr = data["itemAddrDTO"]
    assert addr["divisionId"] == 110105
    assert addr["prov"] == "北京"
    assert addr["city"] == "北京"
    assert addr["gps"] == "116.4,39.9"
