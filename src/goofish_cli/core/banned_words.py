"""发布违禁词门禁：提交前强制检查标题/描述/类目，命中即中止。

移植自 xianyu-seller 技能的发布前第一道门：
- 英文不区分大小写；
- 同时检查「去空白」文本，防止 "Chat GPT" 拆词绕过；
- 内置字典四组（AI 品牌 / 站外导流 / 极限词 / 违法侵权），用户可在
  `~/.goofish-cli/banned_words.txt` 追加（每行一词，# 注释，空行跳过）。

设计原则：宁可多列，命中后由人工判断是否真的需要；新违禁词直接追加到用户字典。
"""
from __future__ import annotations

from pathlib import Path

from goofish_cli.core.errors import GoofishError

# 用户追加字典路径（内置字典不可被用户删除，只能追加）
USER_DICTIONARY = Path.home() / ".goofish-cli" / "banned_words.txt"

# ── AI 品牌 / 竞品平台词（境外品牌 + 主流 AI 名称，平台限流/下架高发）──
_AI_BRANDS = [
    "ChatGPT", "Chat GPT", "GPT", "OpenAI", "Claude", "Anthropic", "Gemini",
    "Bard", "Copilot", "Midjourney", "Stable Diffusion", "Sora", "Perplexity",
    "DeepSeek", "豆包", "通义", "文心一言", "文心", "Kimi", "智谱",
    "讯飞星火", "星火大模型",
]

# ── 站外导流（闲鱼硬红线）──
_OFFSITE = [
    "微信", "weixin", "VX", "V信", "wx号", "加V", "公众号", "二维码",
    "支付宝转", "闲鱼外", "线下交易", "私人收款",
]

# ── 极限词 / 虚假承诺（广告法 + 平台规则）──
_HYPERBOLE = [
    "第一", "最强", "全网最", "国家级", "顶级", "绝对", "百分百", "100%",
    "包过", "包赚", "稳赚", "躺赚", "保本",
]

# ── 违法违规 / 侵权风险 ──
_ILLEGAL = [
    "破解", "盗版", "翻录", "外挂", "代考", "代写论文", "枪手", "脚本号",
    "翻墙", "VPN", "科学上网", "内幕", "报销", "发票",
]

BANNED_WORDS: list[str] = _AI_BRANDS + _OFFSITE + _HYPERBOLE + _ILLEGAL


def load_user_words(path: Path = USER_DICTIONARY) -> list[str]:
    """读用户追加字典：每行一个词，# 注释，空行跳过；缺失返回空列表。"""
    if not path.exists():
        return []
    words: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        words.append(line)
    return words


def check_banned_words(
    texts: list[str], extra: list[str] | None = None
) -> list[str]:
    """检查文本是否命中违禁词，返回命中词列表（去重、保序）。

    英文不区分大小写；同时检查去空白后的文本（防 "Chat GPT" 拆词绕过）。
    """
    joined = "\n".join(t for t in texts if t)
    if not joined.strip():
        return []
    squashed = "".join(joined.split())
    lowered = joined.lower()
    squashed_lower = squashed.lower()

    hits: list[str] = []
    for word in [*BANNED_WORDS, *(extra or [])]:
        wl = word.lower()
        if (wl in lowered or wl in squashed_lower) and word not in hits:
            hits.append(word)
    return hits


def guard(texts: list[str], *, extra: list[str] | None = None) -> list[str]:
    """发布/编辑提交前强制门禁：命中即抛 GoofishError 中止；未命中返回命中列表（空）。

    `texts` 通常为 [标题, 描述, 类目名]。
    """
    hits = check_banned_words(texts, extra)
    if hits:
        raise GoofishError(
            "标题/描述/类目命中违禁词，已中止提交："
            + "、".join(hits)
            + "。请删改命中词；确认为误报可在 ~/.goofish-cli/banned_words.txt "
            "删除对应行（内置词不可删，可忽略该提示手动确认后用其他方式发布）",
            hint="banned_words",
        )
    return hits


__test__ = {"check_banned_words": check_banned_words, "load_user_words": load_user_words}
