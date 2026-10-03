from dataclasses import dataclass
from functools import lru_cache

from babel import Locale
import pycountry


@dataclass(frozen=True)
class Indicator:
    code: str
    name: str
    unit: str
    format_kind: str = "number"
    family: str = "其他"
    definition: str = ""
    comparison_note: str = ""

    @property
    def source_url(self) -> str:
        return f"https://data.worldbank.org/indicator/{self.code}"


INDICATORS = (
    Indicator("NY.GDP.MKTP.CD", "国内生产总值", "现价美元", "usd", "经济规模", "当年国内生产总值按当年汇率折算为美元。", "受价格水平与汇率影响；不能直接衡量实际增长或生活水平。"),
    Indicator("NY.GDP.MKTP.KD.ZG", "实际GDP增速", "%", "percent", "经济增长", "以不变价 GDP 计算的年度同比增长率。", "可比较增长方向；各国修订和统计口径仍可能不同。"),
    Indicator("NY.GDP.PCAP.CD", "人均 GDP", "现价美元", "usd", "经济规模", "当年美元计价的 GDP 除以人口。", "并非购买力平价指标；汇率变化可改变排名。"),
    Indicator("FP.CPI.TOTL.ZG", "消费者价格涨幅", "%", "percent", "价格", "消费者价格指数的年度涨幅。", "消费篮子与统计方法各国不同。"),
    Indicator("SL.UEM.TOTL.ZS", "失业率（ILO 模型估计）", "%", "percent", "劳动力", "劳动力中失业人口的比例，采用国际劳工组织 ILO 模型估计口径。", "属于协调后的模型估计；与各国官方调查读数可能不同。"),
    Indicator("NE.EXP.GNFS.ZS", "商品与服务出口占 GDP", "%", "percent", "外部部门", "国民账户商品与服务出口相对于 GDP 的比例。", "含服务贸易；与海关商品出口额口径不同。"),
    Indicator("NE.IMP.GNFS.ZS", "商品与服务进口占 GDP", "%", "percent", "外部部门", "国民账户商品与服务进口相对于 GDP 的比例。", "含服务贸易；与海关商品进口额口径不同。"),
    Indicator("BX.KLT.DINV.WD.GD.ZS", "外商直接投资净流入占 GDP", "%", "percent", "投资", "外国直接投资净流入相对于 GDP 的比例。", "净流入可为负；不能将其解释为资产收益。"),
    Indicator("NV.IND.MANF.ZS", "制造业增加值占 GDP", "%", "percent", "产业结构", "制造业增加值相对于 GDP 的比例。", "行业范围与增加值估计方法可能不同。"),
    Indicator("SP.POP.TOTL", "人口", "人", "count", "人口", "年中总人口估计。", "人口估计会随普查及模型修订。"),
    Indicator("BN.CAB.XOKA.GD.ZS", "经常账户余额占 GDP", "%", "percent", "外部部门", "国际收支经常账户余额相对于 GDP 的比例。", "盈余与赤字反映外部收支，不能单独判断经济质量。"),
    Indicator("NE.GDI.TOTL.ZS", "资本形成总额占 GDP", "%", "percent", "投资", "国民账户资本形成总额相对于 GDP 的比例。", "包含存货变化；不能等同于金融资产投资收益。"),
    Indicator("FR.INR.RINR", "实际利率", "%", "percent", "金融条件", "世界银行发布的年度实际利率指标。", "利率口径和物价调整方式需查看源指标定义；缺失覆盖较多。"),
    Indicator("GC.DOD.TOTL.GD.ZS", "中央政府债务占 GDP", "%", "percent", "财政", "中央政府债务总额相对于 GDP 的比例。", "不覆盖所有地方政府或广义公共部门债务；国家间不可直接等同。"),
)
INDICATOR_BY_CODE = {indicator.code: indicator for indicator in INDICATORS}

REGION_ZH = {
    "East Asia & Pacific": "东亚与太平洋",
    "Europe & Central Asia": "欧洲与中亚",
    "Latin America & Caribbean": "拉丁美洲与加勒比",
    "Middle East, North Africa, Afghanistan & Pakistan": "中东、北非、阿富汗与巴基斯坦",
    "North America": "北美",
    "South Asia": "南亚",
    "Sub-Saharan Africa": "撒哈拉以南非洲",
}
INCOME_ZH = {
    "High income": "高收入",
    "Upper middle income": "中高收入",
    "Lower middle income": "中低收入",
    "Low income": "低收入",
}

COUNTRY_ZH = {
    "CHN": "中国", "USA": "美国", "DEU": "德国", "JPN": "日本", "IND": "印度",
    "GBR": "英国", "FRA": "法国", "ITA": "意大利", "CAN": "加拿大", "BRA": "巴西",
    "KOR": "韩国", "AUS": "澳大利亚", "IDN": "印度尼西亚", "MEX": "墨西哥",
    "RUS": "俄罗斯", "SAU": "沙特阿拉伯", "ZAF": "南非", "TUR": "土耳其",
    "VNM": "越南", "SGP": "新加坡", "MYS": "马来西亚", "THA": "泰国",
    "NLD": "荷兰", "CHE": "瑞士", "SWE": "瑞典", "ESP": "西班牙",
    "POL": "波兰", "ARE": "阿联酋", "ARG": "阿根廷", "EGY": "埃及",
    "HKG": "中国香港", "TWN": "中国台湾", "MAC": "中国澳门",
    "UVK": "科索沃",
}


@lru_cache(maxsize=1)
def _chinese_territories():
    return Locale.parse("zh_CN").territories


def country_label(code: str, fallback: str = "") -> str:
    name = COUNTRY_ZH.get(code)
    if name is None:
        country = pycountry.countries.get(alpha_3=code)
        if country is not None:
            name = _chinese_territories().get(country.alpha_2)
    name = name or fallback or code
    return f"{name}（{code}）"


def group_label(value: str, group_column: str | None) -> str:
    if group_column == "region":
        return REGION_ZH.get(value.strip(), value)
    if group_column == "income_level":
        return INCOME_ZH.get(value.strip(), value)
    return "所有经济体"
