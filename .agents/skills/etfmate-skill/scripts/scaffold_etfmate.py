#!/usr/bin/env python
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path


TEMPLATES: dict[str, str] = {
    "pyproject.toml": r'''
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "etfmate"
version = "0.1.0"
description = "本地 ETF 持仓与网格交易辅助分析工具"
requires-python = ">=3.10"
dependencies = [
  "playwright",
  "pandas",
  "stockstats",
  "requests",
  "mootdx",
  "pydantic",
  "rich",
  "jinja2",
]

[project.scripts]
etfmate = "etfmate.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
''',
    "src/etfmate/__init__.py": r'''
__version__ = "0.1.0"
''',
    "src/etfmate/storage/models.py": r'''
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Position:
    code: str
    name: str
    quantity: float
    available_quantity: float | None
    cost_price: float
    last_price: float
    market_value: float
    pnl: float
    pnl_pct: float
    source: str = "ths"


@dataclass
class Trade:
    trade_date: str
    trade_time: str | None
    code: str
    name: str
    side: str
    price: float
    quantity: float
    amount: float
    fee: float | None
    source: str = "ths"


@dataclass
class GridConfig:
    code: str
    name: str
    enabled: bool
    base_price: float | None = None
    lower_price: float | None = None
    upper_price: float | None = None
    grid_step_pct: float | None = None
    grid_step_amount: float | None = None
    order_amount: float | None = None
    last_trigger_time: str | None = None


@dataclass
class MarketSnapshot:
    code: str
    name: str
    last_price: float
    pct_chg: float
    volume: float
    amount: float
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    boll_upper: float | None = None
    boll_mid: float | None = None
    boll_lower: float | None = None
    atr14: float | None = None
    atr14_pct: float | None = None
    bias6: float | None = None
    bias12: float | None = None
    bias24: float | None = None
    vol_ma5: float | None = None
    vol_ma20: float | None = None
    data_quality: str = "ok"


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value
''',
    "src/etfmate/storage/repository.py": r'''
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import to_dict


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_id_str(value: str | None = None) -> str:
    return value or datetime.now().strftime("%Y%m%d-%H%M%S")


def write_json(path: Path, payload: Any) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(to_dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
''',
    "src/etfmate/browser/session.py": r'''
from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


DESKTOP_VIEWPORT = {"width": 1280, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}
DEFAULT_CDP_URL = "http://127.0.0.1:9222"


class BrowserSession:
    def __init__(self, root: Path, mobile: bool = False, cdp_url: str | None = None, wait_seconds: int = 90):
        self.root = root
        self.profile_dir = root / "runtime/chrome-cdp-profile"
        self.mobile = mobile
        self.cdp_url = cdp_url or os.environ.get("ETFMATE_CDP_URL", DEFAULT_CDP_URL)
        self.wait_seconds = wait_seconds
        self._playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self) -> "BrowserSession":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._wait_for_cdp()
        self.browser = self._playwright.chromium.connect_over_cdp(self.cdp_url)
        self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._playwright:
            self._playwright.stop()

    def page(self) -> Page:
        if not self.context:
            raise RuntimeError("BrowserSession 尚未启动")
        if self._page and not self._page.is_closed():
            return self._page
        self._page = self.context.new_page()
        self._page.set_viewport_size(MOBILE_VIEWPORT if self.mobile else DESKTOP_VIEWPORT)
        return self._page

    def _wait_for_cdp(self) -> None:
        deadline = time.monotonic() + self.wait_seconds
        printed = False
        while time.monotonic() < deadline:
            if _cdp_available(self.cdp_url):
                return
            if not printed:
                print(_remote_debugging_help(self.profile_dir, self.cdp_url))
                printed = True
            time.sleep(2)
        raise RuntimeError("无法连接 Chrome CDP。请按上方提示打开允许远程调试的 Chrome 后重试。")


def _cdp_available(cdp_url: str) -> bool:
    try:
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=1):
            return True
    except (OSError, urllib.error.URLError):
        return False


def _remote_debugging_help(profile_dir: Path, cdp_url: str) -> str:
    return f"""未连接到 Chrome CDP：{cdp_url}
请打开一个独立调试用 Chrome，避免污染日常浏览器并减少“允许远程调试吗？”反复确认：

PowerShell:
& "$env:ProgramFiles\\Google\\Chrome\\Application\\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="{profile_dir}"

然后在该 Chrome 中打开 chrome://inspect/#remote-debugging，开启 Allow remote debugging for this browser instance。
完成后保持 Chrome 打开，本程序会继续等待连接。"""


def ensure_login(page: Page, url: str, login_check: Callable[[Page], bool], prompt: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if login_check(page):
        return
    print(prompt)
    input("完成后回到终端按 Enter 继续...")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if not login_check(page):
        raise RuntimeError("登录状态仍未通过检查，请确认网页已完成登录和验证")
''',
    "src/etfmate/browser/ths_account.py": r'''
from __future__ import annotations

import json
from pathlib import Path

from .session import BrowserSession, ensure_login


THS_URL = "https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO"


def ths_login_check(page) -> bool:
    text = page.locator("body").inner_text(timeout=5000)
    negative = ["验证码", "手机号登录", "立即登录"]
    positive = ["持仓", "资产", "成交", "盈亏"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with BrowserSession(root) as session:
        ensure_login(
            session.page(),
            THS_URL,
            ths_login_check,
            "请在打开的浏览器窗口中完成同花顺登录和验证码验证。",
        )


def collect(root: Path, out_dir: Path) -> dict:
    captures: list[dict] = []
    with BrowserSession(root) as session:
        page = session.page()
        page.on("response", lambda r: captures.append({"url": r.url, "status": r.status}) if "json" in (r.headers.get("content-type", "")) else None)
        ensure_login(page, THS_URL, ths_login_check, "请在打开的浏览器窗口中完成同花顺登录。")
        page.wait_for_timeout(3000)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "account.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "account.png"), full_page=True)
        (out_dir / "network.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"positions": [], "trades": [], "closed_positions": [], "network": captures}
''',
    "src/etfmate/browser/touker_grid.py": r'''
from __future__ import annotations

import json
from pathlib import Path

from .session import BrowserSession, ensure_login


TOUKER_URL = "https://m.touker.com/fd/conditions/monitoring"


def touker_login_check(page) -> bool:
    text = page.locator("body").inner_text(timeout=5000)
    negative = ["登录", "验证码", "手机号"]
    positive = ["监控", "网格", "条件", "触发"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with BrowserSession(root, mobile=True) as session:
        ensure_login(session.page(), TOUKER_URL, touker_login_check, "请在打开的移动端浏览器窗口中完成 Touker 登录。")


def collect(root: Path, out_dir: Path) -> dict:
    captures: list[dict] = []
    with BrowserSession(root, mobile=True) as session:
        page = session.page()
        page.on("response", lambda r: captures.append({"url": r.url, "status": r.status}) if "json" in (r.headers.get("content-type", "")) else None)
        ensure_login(page, TOUKER_URL, touker_login_check, "请在打开的移动端浏览器窗口中完成 Touker 登录。")
        page.wait_for_timeout(3000)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "grids.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "grids.png"), full_page=True)
        (out_dir / "network.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"grids": [], "network": captures}
''',
    "src/etfmate/market/providers.py": r'''
from __future__ import annotations

import urllib.request


def normalize_etf_code(code: str) -> str:
    value = code.strip().lower()
    if value.startswith(("sh", "sz", "bj")):
        value = value[2:]
    if "." in value:
        value = value.split(".", 1)[0]
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 6:
        raise ValueError(f"无法识别 ETF 代码: {code}")
    return digits


def market_prefix(code: str) -> str:
    code = normalize_etf_code(code)
    if code.startswith(("5", "6", "9")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    normalized = [normalize_etf_code(code) for code in codes]
    if not normalized:
        return {}
    query = ",".join(f"{market_prefix(code)}{code}" for code in normalized)
    req = urllib.request.Request("https://qt.gtimg.cn/q=" + query)
    req.add_header("User-Agent", "Mozilla/5.0")
    raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk", errors="ignore")
    result: dict[str, dict] = {}
    for line in raw.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 50:
            continue
        code = key[2:]
        result[code] = {
            "code": code,
            "name": vals[1],
            "last_price": _float(vals[3]),
            "pct_chg": _float(vals[32]),
            "volume": _float(vals[36]),
            "amount": _float(vals[37]) * 10000,
            "amplitude_pct": _float(vals[43]),
            "turnover_pct": _float(vals[38]),
            "vol_ratio": _float(vals[49]),
        }
    return result


def _float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
''',
    "src/etfmate/market/indicators.py": r'''
from __future__ import annotations

import pandas as pd


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"K 线缺少字段: {', '.join(sorted(missing))}")
    out = df.copy()
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    volume = out["volume"].astype(float)

    for window in (5, 10, 20, 60):
        out[f"ma{window}"] = close.rolling(window).mean()
    out["vol_ma5"] = volume.rolling(5).mean()
    out["vol_ma20"] = volume.rolling(20).mean()

    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    out["boll_mid"] = mid
    out["boll_upper"] = mid + 2 * std
    out["boll_lower"] = mid - 2 * std

    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    out["atr14"] = tr.rolling(14).mean()
    out["atr14_pct"] = out["atr14"] / close * 100

    for window in (6, 12, 24):
        ma = close.rolling(window).mean()
        out[f"bias{window}"] = (close - ma) / ma * 100
    return out
''',
    "src/etfmate/analysis/grid_advisor.py": r'''
from __future__ import annotations

from etfmate.storage.models import GridConfig, MarketSnapshot


def advise_grid(grid: GridConfig, market: MarketSnapshot) -> dict:
    reasons: list[str] = []
    action = "维持"
    if grid.grid_step_pct and market.atr14_pct:
        if grid.grid_step_pct < 0.6 * market.atr14_pct:
            action = "调宽网格"
            reasons.append("当前网格间距小于 0.6 倍 ATR14，容易产生噪音交易")
        elif grid.grid_step_pct > 1.8 * market.atr14_pct:
            action = "调窄网格"
            reasons.append("当前网格间距大于 1.8 倍 ATR14，触发频率可能过低")
        else:
            reasons.append("当前网格间距与 ATR14 波动率基本匹配")
    if market.ma60 and market.last_price < market.ma60 and grid.enabled:
        action = "暂停网格" if action == "维持" else action
        reasons.append("价格低于 MA60，需要防止下跌趋势中机械补仓")
    if not reasons:
        reasons.append("缺少完整波动率或网格参数，建议先补齐数据")
    return {"code": grid.code, "name": grid.name, "action": action, "reasons": reasons}
''',
    "src/etfmate/analysis/recommendation.py": r'''
from __future__ import annotations

from etfmate.storage.models import GridConfig, MarketSnapshot, Position


def recommend(position: Position | None, grid: GridConfig | None, market: MarketSnapshot) -> dict:
    action = "持有"
    reasons: list[str] = []
    risks: list[str] = []

    if market.boll_lower and market.last_price <= market.boll_lower * 1.02 and (market.bias6 or 0) < -3:
        action = "分批买入" if position else "买入"
        reasons.append("价格接近 BOLL 下轨且 BIAS6 明显负偏离")
    elif market.boll_upper and market.last_price >= market.boll_upper * 0.98 and (market.bias6 or 0) > 3:
        action = "减仓"
        reasons.append("价格接近 BOLL 上轨且短线正偏离较大")
    elif market.ma60 and market.last_price < market.ma60 and grid and grid.enabled:
        action = "暂停网格"
        risks.append("价格低于 MA60，网格下沿补仓风险上升")
    else:
        reasons.append("趋势和波动暂未触发强动作信号")

    if market.data_quality != "ok":
        risks.append(f"行情数据完整性: {market.data_quality}")

    return {
        "code": market.code,
        "name": market.name,
        "current_status": _status(position, grid, market),
        "action": action,
        "reasons": reasons,
        "risks": risks or ["暂无明显新增风险"],
        "watch_price": _watch_price(market),
    }


def _status(position: Position | None, grid: GridConfig | None, market: MarketSnapshot) -> str:
    parts = [f"现价 {market.last_price:.3f}，涨跌幅 {market.pct_chg:.2f}%"]
    if position:
        parts.append(f"持仓 {position.quantity:g} 份，浮盈亏 {position.pnl_pct:.2f}%")
    if grid:
        parts.append("网格已启用" if grid.enabled else "网格暂停")
    return "；".join(parts)


def _watch_price(market: MarketSnapshot) -> str:
    prices = []
    if market.boll_lower:
        prices.append(f"BOLL 下轨 {market.boll_lower:.3f}")
    if market.ma20:
        prices.append(f"MA20 {market.ma20:.3f}")
    if market.boll_upper:
        prices.append(f"BOLL 上轨 {market.boll_upper:.3f}")
    return " / ".join(prices) if prices else "等待补齐 K 线指标"
''',
    "src/etfmate/analysis/trade_reviewer.py": r'''
from __future__ import annotations

from etfmate.storage.models import Trade


def review_trades(trades: list[Trade]) -> dict:
    score = 6
    positives: list[str] = []
    problems: list[str] = []

    if not trades:
        return {
            "score": 6,
            "positives": ["今日无交易，避免了无效操作"],
            "problems": ["无交易样本，无法评估买卖点质量"],
            "improvement": "保持记录完整，等待有交易日再复盘",
            "tomorrow_plan": "按网格和趋势条件执行，不追涨杀跌",
        }

    if len(trades) <= 5:
        score += 1
        positives.append("交易频率可控")
    else:
        score -= 1
        problems.append("交易笔数偏多，需要检查手续费和策略偏离")

    total_amount = sum(trade.amount for trade in trades)
    if total_amount > 0:
        positives.append(f"已记录成交金额 {total_amount:.2f} 元")

    score = max(0, min(10, score))
    return {
        "score": score,
        "positives": positives or ["交易记录完整"],
        "problems": problems or ["需要结合技术指标进一步评价买卖点"],
        "improvement": "逐笔标注是否符合网格触发条件",
        "tomorrow_plan": "先确认仓位上限，再决定是否加仓或调参",
    }
''',
    "src/etfmate/report/daily_report.py": r'''
from __future__ import annotations

from pathlib import Path


def render_markdown(analysis_time: str, recommendations: list[dict], grid_advices: list[dict], trade_review: dict) -> str:
    lines = [f"# ETFMate 实时分析 {analysis_time}", ""]
    lines.extend(["## 持仓与网格建议", ""])
    if not recommendations:
        lines.append("暂无可分析 ETF，需先完成采集或导入 raw 数据。")
    for item in recommendations:
        lines.extend([
            f"### {item['code']} {item['name']}",
            f"当前状态：{item['current_status']}",
            f"建议动作：{item['action']}",
            "建议理由：" + "；".join(item["reasons"]),
            "风险点：" + "；".join(item["risks"]),
            f"下一步观察价位：{item['watch_price']}",
            "",
        ])

    lines.extend(["## 网格参数评估", ""])
    for item in grid_advices:
        lines.extend([
            f"- {item['code']} {item['name']}：{item['action']}。理由：" + "；".join(item["reasons"])
        ])
    if not grid_advices:
        lines.append("暂无网格配置数据。")

    lines.extend([
        "",
        "## 交易复盘",
        "",
        f"今日评分：{trade_review['score']}/10",
        "优点：" + "；".join(trade_review["positives"]),
        "问题：" + "；".join(trade_review["problems"]),
        f"最需要改进的一点：{trade_review['improvement']}",
        f"明日计划：{trade_review['tomorrow_plan']}",
        "",
    ])
    return "\n".join(lines)


def write_report(path: Path, analysis_time: str, recommendations: list[dict], grid_advices: list[dict], trade_review: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(analysis_time, recommendations, grid_advices, trade_review), encoding="utf-8")
    return path
''',
    "src/etfmate/cli.py": r'''
from __future__ import annotations

import argparse
from pathlib import Path

from etfmate.analysis.trade_reviewer import review_trades
from etfmate.browser import ths_account, touker_grid
from etfmate.report.daily_report import write_report
from etfmate.storage.repository import run_id_str, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etfmate")
    parser.add_argument("--root", default=".", help="项目根目录")
    sub = parser.add_subparsers(dest="cmd", required=True)

    login = sub.add_parser("login")
    login.add_argument("site", choices=["ths", "touker"])

    collect = sub.add_parser("collect")
    collect.add_argument("--run-id")

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--run-id", required=True)

    report = sub.add_parser("report")
    report.add_argument("--run-id", required=True)

    run = sub.add_parser("run")
    run.add_argument("--run-id")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    run_id = run_id_str(getattr(args, "run_id", None))

    if args.cmd == "login":
        ths_account.login(root) if args.site == "ths" else touker_grid.login(root)
        return 0
    if args.cmd == "collect":
        run_collect(root, run_id)
        return 0
    if args.cmd == "analyze":
        run_analyze(root, args.run_id)
        return 0
    if args.cmd == "report":
        run_report(root, args.run_id)
        return 0
    if args.cmd == "run":
        run_collect(root, run_id)
        run_analyze(root, run_id)
        run_report(root, run_id)
        return 0
    return 1


def run_collect(root: Path, run_id: str) -> None:
    ths = ths_account.collect(root, root / "data/raw/ths" / run_id)
    touker = touker_grid.collect(root, root / "data/raw/touker" / run_id)
    write_json(root / "data/raw/ths" / run_id / "account.json", ths)
    write_json(root / "data/raw/touker" / run_id / "grids.json", touker)


def run_analyze(root: Path, run_id: str) -> None:
    payload = {
        "run_id": run_id,
        "recommendations": [],
        "grid_advices": [],
        "trade_review": review_trades([]),
    }
    write_json(root / "data/raw/market" / run_id / "analysis.json", payload)
    print(f"已生成实时分析占位结果: data/raw/market/{run_id}/analysis.json")


def run_report(root: Path, run_id: str) -> None:
    review = review_trades([])
    out = write_report(root / "data/reports" / f"{run_id}-etf-realtime.md", run_id, [], [], review)
    print(f"已生成报告: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "src/etfmate/browser/__init__.py": "",
    "src/etfmate/market/__init__.py": "",
    "src/etfmate/analysis/__init__.py": "",
    "src/etfmate/report/__init__.py": "",
    "src/etfmate/storage/__init__.py": "",
    "tests/test_market_providers.py": r'''
from etfmate.market.providers import market_prefix, normalize_etf_code


def test_normalize_etf_code():
    assert normalize_etf_code("510300") == "510300"
    assert normalize_etf_code("sh510300") == "510300"
    assert normalize_etf_code("510300.SH") == "510300"


def test_market_prefix():
    assert market_prefix("510300") == "sh"
    assert market_prefix("159915") == "sz"
''',
    "tests/test_grid_advisor.py": r'''
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.storage.models import GridConfig, MarketSnapshot


def test_grid_too_dense():
    grid = GridConfig(code="510300", name="沪深300ETF", enabled=True, grid_step_pct=0.3)
    market = MarketSnapshot(code="510300", name="沪深300ETF", last_price=4, pct_chg=0, volume=1, amount=1, atr14_pct=1)
    assert advise_grid(grid, market)["action"] == "调宽网格"
''',
}


def normalize_template(text: str) -> str:
    return textwrap.dedent(text).strip() + "\n"


def write_file(root: Path, relative: str, text: str, force: bool) -> bool:
    path = root / relative
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize_template(text), encoding="utf-8")
    return True


def patch_gitignore(root: Path) -> bool:
    path = root / ".gitignore"
    required = ["runtime/", "data/raw/", "data/reports/*.html", ".env"]
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [line for line in required if line not in existing.splitlines()]
    if not missing:
        return False
    addition = "\n# ETFMate local runtime data\n" + "\n".join(missing) + "\n"
    path.write_text(existing.rstrip() + "\n" + addition, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 ETFMate Python 项目骨架")
    parser.add_argument("--root", default=".", help="目标项目根目录")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的模板文件")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    skipped: list[str] = []
    for relative, text in TEMPLATES.items():
        if write_file(root, relative, text, args.force):
            created.append(relative)
        else:
            skipped.append(relative)

    if patch_gitignore(root):
        created.append(".gitignore entries")

    print("ETFMate 项目骨架处理完成")
    print(f"创建/更新: {len(created)}")
    for item in created:
        print(f"  + {item}")
    if skipped:
        print(f"保留已有文件: {len(skipped)}")
        for item in skipped:
            print(f"  = {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
