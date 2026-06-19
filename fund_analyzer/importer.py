"""导入工具：基金代码自动补全、截图 OCR 解析、批量导入。"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# OCR 延迟导入（避免 pytesseract 未安装时 import 失败）
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False


# ---------------------------------------------------------------------------
# 基金代码 → 信息的自动推断
# ---------------------------------------------------------------------------

@dataclass
class FundInfo:
    code: str
    name: str
    asset_class: str          # AssetClass 枚举值
    tracking_index: Optional[str] = None
    tracking_lag_days: int = 1
    annual_fee: float = 0.006  # 默认 QDII 约 0.6%


# 名称关键词 → 资产大类
ASSET_KEYWORDS: List[Tuple[List[str], str]] = [
    (["纳斯达克", "纳指", "nasdaq", "科技股"], "us_equity"),
    (["标普", "s&p", "sp500", "美股"], "us_equity"),
    (["道琼斯", "道指"], "us_equity"),
    (["费城半导体", "半导体", "芯片etf"], "us_equity"),
    (["沪深300", "中证500", "上证50", "创业板", "科创", "a股"], "cn_equity"),
    (["恒生", "港股", "香港", "h股"], "hk_equity"),
    (["黄金", "原油", "商品", "大宗"], "commodity"),
    (["债券", "纯债", "国债", "信用债", "利率债", "全债"], "bond"),
    (["货币", "现金", "活期"], "cash"),
    (["全球", "世界", "msci", "发达国家"], "global_equity"),
]

# 名称关键词 → 跟踪指数
TRACKING_MAP: List[Tuple[List[str], Dict]] = [
    (["纳斯达克100", "纳指100", "ndx", "nasdaq100"], {"index": "^NDX", "lag_days": 2}),
    (["纳斯达克", "纳指", "nasdaq"], {"index": "^IXIC", "lag_days": 2}),
    (["标普500", "s&p500", "sp500", "标普 500", "标普500"], {"index": "^GSPC", "lag_days": 1}),
    (["道琼斯", "道指"], {"index": "^DJI", "lag_days": 1}),
    (["费城半导体", "sox"], {"index": "^SOX", "lag_days": 2}),
]


def infer_asset_class(name: str) -> str:
    name_lower = name.lower()
    for keywords, cls in ASSET_KEYWORDS:
        for kw in keywords:
            if kw.lower() in name_lower:
                return cls
    return "other"


def infer_tracking(name: str) -> Dict:
    """返回 {'index': '^NDX', 'lag_days': 2} 或空 dict。"""
    name_lower = name.lower()
    for keywords, cfg in TRACKING_MAP:
        for kw in keywords:
            if kw.lower() in name_lower:
                return dict(cfg)
    return {}


def infer_annual_fee(name: str, asset_class: str) -> float:
    """根据基金类型给默认费率。"""
    fee_map = {
        "us_equity": 0.008, "cn_equity": 0.005, "hk_equity": 0.007,
        "global_equity": 0.008, "commodity": 0.01, "bond": 0.003, "cash": 0.0,
    }
    return fee_map.get(asset_class, 0.006)


def search_fund(code: str, em) -> Optional[FundInfo]:
    """输入代码，从天天基金获取实时信息并自动推断。

    em 是 EastMoney 实例。
    返回 FundInfo 或 None。
    """
    quote = em.realtime(code)
    if not quote or not quote.name:
        return None
    name = quote.name
    ac = infer_asset_class(name)
    tk = infer_tracking(name)
    fee = infer_annual_fee(name, ac)
    return FundInfo(
        code=code,
        name=name,
        asset_class=ac,
        tracking_index=tk.get("index"),
        tracking_lag_days=tk.get("lag_days", 1),
        annual_fee=fee,
    )


# ---------------------------------------------------------------------------
# 批量导入：解析 "代码 金额" 行
# ---------------------------------------------------------------------------

def parse_code_amount_line(line: str) -> Optional[Tuple[str, float]]:
    """解析 "270042 50000" 或 "270042\t50000.5" 格式的一行。"""
    line = line.strip()
    if not line:
        return None
    m = re.match(r'(\d{6})\s+([\d.]+)', line)
    if not m:
        return None
    return m.group(1), float(m.group(2))


def parse_batch_text(text: str) -> List[Tuple[str, float]]:
    """解析多行批量文本，返回 [(code, amount), ...]。"""
    results = []
    for line in text.strip().splitlines():
        parsed = parse_code_amount_line(line)
        if parsed:
            results.append(parsed)
    return results


# ---------------------------------------------------------------------------
# 截图 OCR（支付宝持仓页）
# ---------------------------------------------------------------------------

def ocr_funds_from_image(image_data: bytes, lang: str = "chi_sim+eng") -> List[Tuple[str, float]]:
    """从支付宝持仓截图 OCR 提取基金代码和金额。

    系统需安装 tesseract-ocr：
      brew install tesseract (macOS)
      apt install tesseract-ocr tesseract-ocr-chi-sim (Linux)
    Python 依赖：pip install pytesseract Pillow
    """
    if not (HAS_PIL and HAS_TESSERACT):
        raise RuntimeError(
            "OCR 需要安装 pytesseract 和 Pillow：pip install pytesseract Pillow\n"
            "以及系统级 tesseract-ocr"
        )

    img = Image.open(io.BytesIO(image_data))
    text = pytesseract.image_to_string(img, lang=lang)

    results = []
    lines = text.splitlines()
    for line in lines:
        # 支付宝截图格式：6位代码 附近有金额数字
        m = re.search(r'(\d{6})[^\d]*?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)', line)
        if m:
            code = m.group(1)
            amount_str = m.group(2).replace(",", "")
            try:
                amount = float(amount_str)
                if 1 < amount < 100_000_000:  # 合理金额范围
                    results.append((code, amount))
            except ValueError:
                continue

    return results
