"""BACI 伙伴与 HS2 商品章的描述性分析。"""

from __future__ import annotations

import pandas as pd


HS_SECTIONS = (
    (1, 5, "动物及动物产品"), (6, 14, "植物产品"), (15, 15, "动植物油脂"),
    (16, 24, "食品饮料与烟草"), (25, 27, "矿物产品"), (28, 38, "化工产品"),
    (39, 40, "塑料与橡胶"), (41, 43, "皮革与毛皮"), (44, 46, "木及木制品"),
    (47, 49, "纸与印刷品"), (50, 63, "纺织品"), (64, 67, "鞋帽与羽毛制品"),
    (68, 70, "石材陶瓷与玻璃"), (71, 71, "珠宝与贵金属"),
    (72, 83, "贱金属及制品"), (84, 85, "机械与电气设备"),
    (86, 89, "运输设备"), (90, 92, "精密仪器与乐器"),
    (93, 93, "武器弹药"), (94, 96, "杂项制品"), (97, 97, "艺术品与古物"),
)

# 按世界海关组织 HS 2017 章目录编写的中文短名称；77 章为保留章。
HS_CHAPTERS = dict(line.split("|", 1) for line in """
01|活动物
02|肉及食用杂碎
03|鱼及水产品
04|乳品、蛋与蜂蜜
05|其他动物产品
06|活植物与花卉
07|蔬菜及块茎
08|水果与坚果
09|咖啡、茶与香料
10|谷物
11|制粉产品与淀粉
12|油籽及其他种子
13|虫胶、树胶与植物汁液
14|植物编结材料
15|动植物油脂
16|肉类及水产品制品
17|糖及糖制品
18|可可及制品
19|谷物、面粉与乳制品
20|蔬果与坚果制品
21|其他食品制品
22|饮料、酒与醋
23|食品工业残渣与饲料
24|烟草及制品
25|盐、硫磺与建材原料
26|矿砂、矿渣与矿灰
27|矿物燃料与石油
28|无机化学品
29|有机化学品
30|医药品
31|肥料
32|染料、颜料与涂料
33|精油、香水与化妆品
34|肥皂、洗涤剂与蜡
35|蛋白质、淀粉与酶
36|炸药与烟火制品
37|摄影与电影用品
38|其他化工产品
39|塑料及制品
40|橡胶及制品
41|生皮与皮革
42|皮革制品与箱包
43|毛皮及制品
44|木材及木制品
45|软木及制品
46|草编与柳编制品
47|木浆与废纸
48|纸及纸制品
49|印刷品与书报
50|丝绸
51|羊毛及动物毛
52|棉花及棉织品
53|其他植物纤维
54|化学纤维长丝
55|化学纤维短纤
56|无纺布、绳索等
57|地毯及铺地制品
58|特种机织物与刺绣
59|涂层纺织物
60|针织或钩编织物
61|针织服装
62|非针织服装
63|其他纺织制成品
64|鞋靴及零件
65|帽类及零件
66|伞、手杖与鞭
67|羽毛制品与人发制品
68|石材、水泥等制品
69|陶瓷产品
70|玻璃及玻璃制品
71|珠宝、贵金属与硬币
72|钢铁
73|钢铁制品
74|铜及制品
75|镍及制品
76|铝及制品
78|铅及制品
79|锌及制品
80|锡及制品
81|其他贱金属与金属陶瓷
82|贱金属工具与餐具
83|其他贱金属制品
84|机械设备及零件
85|电气设备及零件
86|铁路车辆与设备
87|汽车等道路车辆
88|航空器与航天器
89|船舶与浮动结构
90|光学、医疗与精密仪器
91|钟表及零件
92|乐器及零件
93|武器弹药及零件
94|家具、灯具与预制建筑
95|玩具、游戏与体育用品
96|其他制成品
97|艺术品与古物
""".strip().splitlines())


def section_name(hs2: str) -> str:
    code = int(hs2)
    return next((name for start, end, name in HS_SECTIONS if start <= code <= end), "其他或未映射")


def chapter_name(hs2: str) -> str:
    return HS_CHAPTERS.get(hs2, "未映射商品章")


def compact_usd(value: float, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else ""
    if abs(value) >= 1e12:
        return f"{sign}{value / 1e12:,.2f}万亿"
    if abs(value) >= 1e8:
        return f"{sign}{value / 1e8:,.1f}亿"
    return f"{sign}{value:,.0f}美元"


def annual_trade_totals(partners: pd.DataFrame, reporter: str) -> pd.DataFrame:
    rows = partners.loc[partners.reporter_code == reporter]
    if rows.empty:
        return pd.DataFrame(columns=["year", "exports_usd", "imports_usd", "balance_usd"])
    totals = rows.groupby(["year", "flow"], as_index=False).trade_usd.sum()
    wide = totals.pivot(index="year", columns="flow", values="trade_usd").fillna(0)
    wide.columns.name = None
    result = wide.rename(columns={"X": "exports_usd", "M": "imports_usd"}).reset_index()
    for col in ("exports_usd", "imports_usd"):
        if col not in result:
            result[col] = 0.0
    result["balance_usd"] = result.exports_usd - result.imports_usd
    return result.sort_values("year").reset_index(drop=True)


def chapter_profile(chapters: pd.DataFrame, reporter: str, year: int, flow: str = "X") -> pd.DataFrame:
    """RCA=本国商品章出口份额/全球该章出口份额；只对出口定义。"""
    if flow not in ("X", "M"):
        raise ValueError("贸易流向必须为 X 或 M")
    selected = chapters.loc[
        (chapters.reporter_code == reporter) & (chapters.year == year) & (chapters.flow == flow),
        ["hs2", "trade_usd"],
    ].copy()
    if selected.empty:
        return selected.assign(section=pd.Series(dtype=str), chapter=pd.Series(dtype=str),
                               share=pd.Series(dtype=float), rca=pd.Series(dtype=float))
    selected["section"] = selected.hs2.map(section_name)
    selected["chapter"] = selected.hs2.map(chapter_name)
    total = selected.trade_usd.sum()
    selected["share"] = selected.trade_usd / total if total > 0 else 0.0
    selected["rca"] = float("nan")
    if flow == "X" and total > 0:
        world = chapters.loc[(chapters.year == year) & (chapters.flow == "X")].groupby("hs2").trade_usd.sum()
        world_total = world.sum()
        if world_total > 0:
            benchmark = selected.hs2.map(world) / world_total
            selected["rca"] = selected.share / benchmark.where(benchmark > 0)
    return selected.sort_values("trade_usd", ascending=False).reset_index(drop=True)
