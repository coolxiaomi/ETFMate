from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from etfmate.storage.models import GridConfig, MarketSnapshot, Position


@dataclass
class LayerEvidence:
    key: str
    name: str
    status: str
    score: int
    conclusion: str
    evidence: list[str]
    risks: list[str]
    missing_reason: str | None = None


@dataclass
class LayeredContext:
    code: str
    confidence: int
    total_score: int
    available_layers: int
    total_layers: int
    layers: list[LayerEvidence]
    summary: str
    missing_layers: list[str]


A_STOCK_LAYERS = [
    ("market", "行情技术层"),
    ("research", "研报预期层"),
    ("signal", "热点信号层"),
    ("capital", "资金筹码层"),
    ("news", "新闻舆情层"),
    ("fundamental", "基础数据层"),
    ("announcement", "公告事件层"),
]


def build_layered_context(
    position: Position | None,
    grid: GridConfig | None,
    market: MarketSnapshot,
    all_positions: list[Position] | None = None,
) -> LayeredContext:
    layers = [
        _market_layer(market),
        _research_layer(),
        _signal_layer(position, all_positions or []),
        _capital_layer(market),
        _news_layer(),
        _fundamental_layer(),
        _announcement_layer(),
    ]
    available_layers = sum(1 for item in layers if item.status in {"已接入", "部分接入"})
    confidence = min(100, max(0, round(sum(_status_weight(item.status) for item in layers) / len(layers))))
    total_score = sum(item.score for item in layers)
    missing_layers = [item.name for item in layers if item.status == "待接入"]
    summary = _summary(total_score, confidence, missing_layers, position, grid)
    return LayeredContext(
        code=market.code,
        confidence=confidence,
        total_score=total_score,
        available_layers=available_layers,
        total_layers=len(layers),
        layers=layers,
        summary=summary,
        missing_layers=missing_layers,
    )


def context_to_dict(context: LayeredContext | None) -> dict[str, Any] | None:
    if context is None:
        return None
    return {
        "code": context.code,
        "confidence": context.confidence,
        "total_score": context.total_score,
        "available_layers": context.available_layers,
        "total_layers": context.total_layers,
        "summary": context.summary,
        "missing_layers": context.missing_layers,
        "layers": [
            {
                "key": item.key,
                "name": item.name,
                "status": item.status,
                "score": item.score,
                "conclusion": item.conclusion,
                "evidence": item.evidence,
                "risks": item.risks,
                "missing_reason": item.missing_reason,
            }
            for item in context.layers
        ],
    }


def normalize_context(context: LayeredContext | dict[str, Any] | None) -> dict[str, Any] | None:
    if context is None:
        return None
    if isinstance(context, LayeredContext):
        return context_to_dict(context)
    return context


def _market_layer(market: MarketSnapshot) -> LayerEvidence:
    score = 0
    evidence: list[str] = []
    risks: list[str] = []

    if market.ma20 and market.last_price >= market.ma20:
        score += 1
        evidence.append("现价站上 MA20")
    elif market.ma20:
        score -= 1
        risks.append("现价低于 MA20")

    if market.ma60 and market.last_price >= market.ma60:
        score += 1
        evidence.append("现价站上 MA60")
    elif market.ma60:
        score -= 2
        risks.append("现价低于 MA60")

    if market.boll_lower and market.last_price <= market.boll_lower * 1.03:
        score += 1
        evidence.append("接近 BOLL 下轨")
    if market.boll_upper and market.last_price >= market.boll_upper * 0.98:
        score -= 1
        risks.append("接近 BOLL 上轨")

    if market.bias6 is not None and market.bias6 <= -4:
        score += 1
        evidence.append("BIAS6 负偏离较深")
    elif market.bias6 is not None and market.bias6 >= 4:
        score -= 1
        risks.append("BIAS6 正偏离偏高")

    if market.vol_ma5 and market.vol_ma20:
        ratio = market.vol_ma5 / market.vol_ma20 if market.vol_ma20 else 0
        evidence.append(f"VOL5/20 {ratio:.2f}倍")
        if ratio < 0.75:
            risks.append("近5日成交低于20日均量")
        elif ratio > 1.2:
            evidence.append("近期成交活跃")

    status = "已接入" if market.data_quality and "missing" not in market.data_quality and "error" not in market.data_quality else "部分接入"
    conclusion = "技术面偏多" if score >= 2 else "技术面偏弱" if score <= -2 else "技术面中性"
    return LayerEvidence("market", "行情技术层", status, _clamp_score(score), conclusion, evidence or ["已有行情/K线快照"], risks)


def _research_layer() -> LayerEvidence:
    return _missing_layer("research", "研报预期层", "尚未接入 a-stock-data 研报/一致预期适配器")


def _signal_layer(position: Position | None, positions: list[Position]) -> LayerEvidence:
    if not position:
        return _missing_layer("signal", "热点信号层", "无持仓名称，暂无法做主题重合启发式；尚未接入热点/北向/板块接口")
    theme = _theme_key(position.name)
    peers = [item for item in positions if item.code != position.code and _theme_key(item.name) == theme] if theme else []
    if peers:
        names = "、".join(f"{item.code} {item.name}" for item in peers[:3])
        return LayerEvidence(
            "signal",
            "热点信号层",
            "部分接入",
            -1,
            "同主题持仓偏集中",
            [f"本地持仓主题：{theme}"],
            [f"可能与 {names} 重合，需结合成分股/规模/费率进一步筛选"],
            "尚未接入 a-stock-data 热点、北向、行业与成分股重合度接口",
        )
    if theme:
        return LayerEvidence(
            "signal",
            "热点信号层",
            "部分接入",
            0,
            "暂未发现本地同主题重复持仓",
            [f"本地持仓主题：{theme}"],
            [],
            "尚未接入 a-stock-data 热点、北向、行业与成分股重合度接口",
        )
    return _missing_layer("signal", "热点信号层", "尚未接入 a-stock-data 热点、北向、行业与成分股重合度接口")


def _capital_layer(market: MarketSnapshot) -> LayerEvidence:
    evidence: list[str] = []
    risks: list[str] = []
    score = 0
    if market.amount:
        evidence.append(f"成交额 {market.amount / 10000:.0f} 万")
    if market.turnover_pct is not None:
        evidence.append(f"换手 {market.turnover_pct:.2f}%")
    if market.vol_ratio is not None:
        evidence.append(f"量比 {market.vol_ratio:.2f}")
        if market.vol_ratio >= 2:
            risks.append("量比放大，需防冲高回落")
            score -= 1
    if market.vol_ma5 and market.vol_ma20:
        ratio = market.vol_ma5 / market.vol_ma20 if market.vol_ma20 else 0
        if ratio > 1.2:
            score += 1
        elif ratio < 0.75:
            score -= 1
    if evidence:
        return LayerEvidence(
            "capital",
            "资金筹码层",
            "部分接入",
            _clamp_score(score),
            "已用成交额/量能近似观察流动性",
            evidence,
            risks,
            "尚未接入 a-stock-data 主力资金、两融、份额/筹码等深层资金数据",
        )
    return _missing_layer("capital", "资金筹码层", "尚未接入 a-stock-data 主力资金、两融、份额/筹码等深层资金数据")


def _news_layer() -> LayerEvidence:
    return _missing_layer("news", "新闻舆情层", "尚未接入 a-stock-data 新闻/资讯适配器")


def _fundamental_layer() -> LayerEvidence:
    return _missing_layer("fundamental", "基础数据层", "尚未接入 a-stock-data 基金规模、费率、跟踪误差、成分权重等基础数据适配器")


def _announcement_layer() -> LayerEvidence:
    return _missing_layer("announcement", "公告事件层", "尚未接入 a-stock-data 公告/事件适配器")


def _missing_layer(key: str, name: str, reason: str) -> LayerEvidence:
    return LayerEvidence(key, name, "待接入", 0, "暂无可验证结论", [], [], reason)


def _status_weight(status: str) -> int:
    if status == "已接入":
        return 100
    if status == "部分接入":
        return 55
    return 0


def _summary(
    total_score: int,
    confidence: int,
    missing_layers: list[str],
    position: Position | None,
    grid: GridConfig | None,
) -> str:
    direction = "偏多" if total_score >= 2 else "偏空" if total_score <= -2 else "中性"
    base = f"七层证据当前置信度 {confidence}%，综合方向 {direction}"
    if missing_layers:
        base += f"，缺少 {'、'.join(missing_layers[:4])}"
    if position and position.note:
        base += "；已纳入你的持仓备注"
    if grid:
        base += "；已结合 Touker 网格参数"
    return base


def _clamp_score(value: int) -> int:
    return max(-3, min(3, value))


def _theme_key(name: str) -> str | None:
    rules = {
        "软件": ("软件", "云计算", "信创"),
        "半导体": ("半导体", "芯片", "集成电路"),
        "新能源": ("新能源", "电池", "储能", "光伏"),
        "有色金属": ("有色", "稀有金属", "工业金属"),
        "科创创业": ("科创创业", "双创"),
        "港股医药": ("港股创新药", "创新药", "医药"),
    }
    for key, words in rules.items():
        if any(word in name for word in words):
            return key
    return None
