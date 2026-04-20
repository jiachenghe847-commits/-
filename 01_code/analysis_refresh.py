"""
Cross-country EV panel refresh pipeline (2013-2024 context, 2015-2024 model window)
------------------------------------------------------------------------------
What this script does:
1) Reads IEA EVDataExplorer file and extracts EV sales/stock share + public chargers.
2) Fetches World Bank GDP PPP and population via wbgapi (with CSV fallback).
3) Builds country-year panel, computes charger growth and lagged growth correctly.
4) Runs FE / TWFE regressions and heterogeneity regressions.
5) Exports updated panel/tables/figures for manuscript synchronization.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import wbgapi as wb
from linearmodels.panel import PanelOLS


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

YEAR_CONTEXT_START = 2013
YEAR_CONTEXT_END = 2024
YEAR_MODEL_START = 2015
YEAR_MODEL_END = 2024

IEA_FILE = "EVDataExplorer2025(4).xlsx"
IEA_SHEET = "GEVO_EV_2025"
BRENT_FILE = "Europe_Brent_Spot_Price_FOB.csv"

OUT_PANEL = "panel_final.csv"
OUT_SAMPLE = "regression_sample_main.csv"
OUT_MAIN = "regression_main.csv"
OUT_HET = "regression_heterogeneity.csv"
OUT_DESC = "descriptive_stats.csv"
OUT_DICT = "variable_dictionary.csv"
OUT_METRICS = "data_coverage_metrics.csv"
OUT_DENSITY_FORM = "density_form_robustness.csv"

FIG1 = "fig1_ev_penetration_trend.png"
FIG2 = "fig2_gdp_vs_penetration.png"
FIG3 = "fig3_chargers_vs_ev.png"
FIG4 = "fig4_heterogeneity.png"

INFRA_VAR = "chargers_per_mn_itp"
INFRA_LABEL_CN = "充电桩密度(每百万人,插值)"


# ---------------------------------------------------------------------------
# Country mapping (IEA name -> ISO3)
# ---------------------------------------------------------------------------

IEA_TO_ISO3: Dict[str, str] = {
    "Australia": "AUS",
    "Austria": "AUT",
    "Belgium": "BEL",
    "Brazil": "BRA",
    "Bulgaria": "BGR",
    "Canada": "CAN",
    "Chile": "CHL",
    "China": "CHN",
    "Colombia": "COL",
    "Costa Rica": "CRI",
    "Croatia": "HRV",
    "Cyprus": "CYP",
    "Czech Republic": "CZE",
    "Denmark": "DNK",
    "Estonia": "EST",
    "Finland": "FIN",
    "France": "FRA",
    "Germany": "DEU",
    "Greece": "GRC",
    "Hungary": "HUN",
    "Iceland": "ISL",
    "India": "IND",
    "Indonesia": "IDN",
    "Ireland": "IRL",
    "Israel": "ISR",
    "Italy": "ITA",
    "Japan": "JPN",
    "Korea": "KOR",
    "Latvia": "LVA",
    "Lithuania": "LTU",
    "Luxembourg": "LUX",
    "Malaysia": "MYS",
    "Mexico": "MEX",
    "Netherlands": "NLD",
    "New Zealand": "NZL",
    "Norway": "NOR",
    "Poland": "POL",
    "Portugal": "PRT",
    "Romania": "ROU",
    "Russia": "RUS",
    "Seychelles": "SYC",
    "Slovakia": "SVK",
    "Slovenia": "SVN",
    "South Africa": "ZAF",
    "Spain": "ESP",
    "Sweden": "SWE",
    "Switzerland": "CHE",
    "Thailand": "THA",
    "Turkiye": "TUR",
    "USA": "USA",
    "United Kingdom": "GBR",
    "Uzbekistan": "UZB",
    "Viet Nam": "VNM",
}

REGIONS = {
    "Africa",
    "Asia Pacific",
    "Central and South America",
    "EU27",
    "Europe",
    "Rest of the world",
    "World",
    "Other Europe",
    "Eurasia",
    "Middle East",
    "Other Asia Pacific",
    "Other Africa",
    "North America",
    "Middle East and Caspian",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def star(p: float) -> str:
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.1:
        return "*"
    return ""


def fmt_coef(model, var: str) -> str:
    if var not in model.params.index:
        return "—"
    return f"{model.params[var]:.3f}{star(model.pvalues[var])}"


def fmt_se(model, var: str) -> str:
    if var not in model.std_errors.index:
        return "—"
    return f"({model.std_errors[var]:.3f})"


def parse_year(v) -> float:
    if pd.isna(v):
        return np.nan
    s = str(v).strip()
    if s.startswith("YR"):
        s = s[2:]
    try:
        return int(s)
    except Exception:
        return np.nan


def fetch_wb_indicator(
    indicator: str, iso3_list: Iterable[str], value_col: str, y0: int, y1: int
) -> pd.DataFrame:
    rows = []
    for r in wb.data.fetch(indicator, economy=list(iso3_list), time=range(y0, y1 + 1)):
        rows.append(
            {
                "iso3c": r.get("economy"),
                "year": parse_year(r.get("time")),
                value_col: r.get("value"),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["iso3c", "year", value_col])
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    return (
        df.dropna(subset=["iso3c", "year"])
        .assign(year=lambda x: x["year"].astype(int))
        .drop_duplicates(["iso3c", "year"])
    )


def load_wb_with_fallback(iso3_list: List[str]) -> pd.DataFrame:
    try:
        gdp = fetch_wb_indicator(
            "NY.GDP.PCAP.PP.CD", iso3_list, "gdp_pc_ppp", YEAR_CONTEXT_START, YEAR_CONTEXT_END
        )
        pop = fetch_wb_indicator(
            "SP.POP.TOTL", iso3_list, "population", YEAR_CONTEXT_START, YEAR_CONTEXT_END
        )
        wb_df = gdp.merge(pop, on=["iso3c", "year"], how="outer")
    except Exception as e:
        print(f"[WARN] wbgapi fetch failed, fallback to local csv. reason: {e}")
        gdp = pd.read_csv("wb_gdp.csv")
        pop = pd.read_csv("wb_pop.csv")
        gdp = gdp.rename(columns={"iso3c": "iso3c", "year": "year", "gdp_pc_ppp": "gdp_pc_ppp"})
        pop = pop.rename(columns={"iso3c": "iso3c", "year": "year", "population": "population"})
        gdp["year"] = pd.to_numeric(gdp["year"], errors="coerce")
        pop["year"] = pd.to_numeric(pop["year"], errors="coerce")
        wb_df = gdp.merge(pop, on=["iso3c", "year"], how="outer")

    econ = wb.economy.DataFrame(iso3_list).reset_index().rename(columns={"id": "iso3c"})
    econ = econ[["iso3c", "name", "incomeLevel"]].rename(columns={"name": "country"})
    wb_df = wb_df.merge(econ, on="iso3c", how="left")
    wb_df["income_group"] = wb_df["incomeLevel"].replace({"LIC": "LMC"}).fillna(wb_df["incomeLevel"])
    wb_df = wb_df.drop(columns=["incomeLevel"])
    return wb_df


def extract_iea(df: pd.DataFrame, param: str, mode: str, powertrain: str, col: str) -> pd.DataFrame:
    x = df[
        (df["parameter"] == param)
        & (df["mode"] == mode)
        & (df["powertrain"] == powertrain)
    ].copy()
    x = x[~x["region_country"].isin(REGIONS)]
    x = x[["region_country", "year", "value"]].rename(
        columns={"region_country": "country_iea", "value": col}
    )
    x["year"] = pd.to_numeric(x["year"], errors="coerce").astype("Int64")
    return x


def build_iea_panel() -> pd.DataFrame:
    ev = pd.read_excel(IEA_FILE, sheet_name=IEA_SHEET)
    hist = ev[ev["category"] == "Historical"].copy()

    sales = extract_iea(hist, "EV sales share", "Cars", "EV", "ev_sales_share_cars")
    stock = extract_iea(hist, "EV stock share", "Cars", "EV", "ev_stock_share_cars")
    ch_fast = extract_iea(hist, "EV charging points", "EV", "Publicly available fast", "chargers_fast")
    ch_slow = extract_iea(hist, "EV charging points", "EV", "Publicly available slow", "chargers_slow")

    chargers = ch_fast.merge(ch_slow, on=["country_iea", "year"], how="outer")
    both_na = chargers["chargers_fast"].isna() & chargers["chargers_slow"].isna()
    chargers["chargers_total"] = chargers[["chargers_fast", "chargers_slow"]].fillna(0).sum(axis=1)
    chargers.loc[both_na, "chargers_total"] = np.nan

    panel = sales.merge(stock, on=["country_iea", "year"], how="outer").merge(
        chargers[["country_iea", "year", "chargers_total", "chargers_fast", "chargers_slow"]],
        on=["country_iea", "year"],
        how="outer",
    )
    panel["iso3c"] = panel["country_iea"].map(IEA_TO_ISO3)
    panel = panel[panel["iso3c"].notna()].drop(columns=["country_iea"])
    panel["year"] = pd.to_numeric(panel["year"], errors="coerce").astype("Int64")
    panel = panel.dropna(subset=["year"]).assign(year=lambda x: x["year"].astype(int))
    panel = panel[(panel["year"] >= YEAR_CONTEXT_START) & (panel["year"] <= YEAR_CONTEXT_END)].copy()
    return panel


def load_brent() -> pd.DataFrame:
    b = pd.read_csv(BRENT_FILE, skiprows=5, names=["month_str", "price"])
    b["year"] = pd.to_datetime(b["month_str"], format="%b %Y", errors="coerce").dt.year
    b["price"] = pd.to_numeric(b["price"], errors="coerce")
    out = b.dropna(subset=["year", "price"]).groupby("year", as_index=False)["price"].mean()
    return out.rename(columns={"price": "brent_usd"})


def run_panel_models(panel_model: pd.DataFrame):
    # Main model samples
    base_vars = ["ev_sales_share_cars", "ln_gdp_pc_ppp", "ln_brent", "ln_population"]
    full_vars = base_vars + [INFRA_VAR]

    d1 = panel_model.dropna(subset=base_vars).set_index(["iso3c", "year"])
    d2 = panel_model.dropna(subset=full_vars).set_index(["iso3c", "year"])
    d4 = panel_model.dropna(subset=["ev_stock_share_cars"] + base_vars[1:] + [INFRA_VAR]).set_index(
        ["iso3c", "year"]
    )
    d5 = panel_model[panel_model["ev_sales_share_cars"] < 80].dropna(subset=full_vars).set_index(["iso3c", "year"])

    results = {}
    results["M1"] = PanelOLS(
        d1["ev_sales_share_cars"], d1[["ln_gdp_pc_ppp", "ln_brent", "ln_population"]], entity_effects=True
    ).fit(cov_type="clustered", cluster_entity=True)
    results["M2"] = PanelOLS(
        d2["ev_sales_share_cars"],
        d2[["ln_gdp_pc_ppp", "ln_brent", "ln_population", INFRA_VAR]],
        entity_effects=True,
    ).fit(cov_type="clustered", cluster_entity=True)
    results["M3"] = PanelOLS(
        d2["ev_sales_share_cars"],
        d2[["ln_gdp_pc_ppp", "ln_population", INFRA_VAR]],
        entity_effects=True,
        time_effects=True,
        drop_absorbed=True,
    ).fit(cov_type="clustered", cluster_entity=True)
    results["M4"] = PanelOLS(
        d4["ev_stock_share_cars"],
        d4[["ln_gdp_pc_ppp", "ln_brent", "ln_population", INFRA_VAR]],
        entity_effects=True,
    ).fit(cov_type="clustered", cluster_entity=True)
    results["M5"] = PanelOLS(
        d5["ev_sales_share_cars"],
        d5[["ln_gdp_pc_ppp", "ln_brent", "ln_population", INFRA_VAR]],
        entity_effects=True,
    ).fit(cov_type="clustered", cluster_entity=True)

    # Heterogeneity
    hic_set = set(panel_model.loc[panel_model["income_group"] == "HIC", "iso3c"].dropna().unique())
    d2r = d2.reset_index()
    d_hic = d2r[d2r["iso3c"].isin(hic_set)].set_index(["iso3c", "year"])
    d_non = d2r[~d2r["iso3c"].isin(hic_set)].set_index(["iso3c", "year"])

    results["M6_HIC"] = PanelOLS(
        d_hic["ev_sales_share_cars"],
        d_hic[["ln_gdp_pc_ppp", "ln_brent", "ln_population", INFRA_VAR]],
        entity_effects=True,
    ).fit(cov_type="clustered", cluster_entity=True)
    results["M7_nonHIC"] = PanelOLS(
        d_non["ev_sales_share_cars"],
        d_non[["ln_gdp_pc_ppp", "ln_brent", "ln_population", INFRA_VAR]],
        entity_effects=True,
    ).fit(cov_type="clustered", cluster_entity=True)

    return results, d2.reset_index(), d_hic.reset_index(), d_non.reset_index()


def save_regression_tables(results, d_hic, d_non):
    # Main table (keep compatibility with original csv style)
    main_rows = [
        ["变量", "", "M1 基准", "", "M2 主模型", "", "M3 双向FE", "", "M4 因变量替换", "", "M5 剔极端值", ""],
        [
            "ln人均GDP",
            "",
            fmt_coef(results["M1"], "ln_gdp_pc_ppp"),
            fmt_se(results["M1"], "ln_gdp_pc_ppp"),
            fmt_coef(results["M2"], "ln_gdp_pc_ppp"),
            fmt_se(results["M2"], "ln_gdp_pc_ppp"),
            fmt_coef(results["M3"], "ln_gdp_pc_ppp"),
            fmt_se(results["M3"], "ln_gdp_pc_ppp"),
            fmt_coef(results["M4"], "ln_gdp_pc_ppp"),
            fmt_se(results["M4"], "ln_gdp_pc_ppp"),
            fmt_coef(results["M5"], "ln_gdp_pc_ppp"),
            fmt_se(results["M5"], "ln_gdp_pc_ppp"),
        ],
        [
            "ln Brent油价",
            "",
            fmt_coef(results["M1"], "ln_brent"),
            fmt_se(results["M1"], "ln_brent"),
            fmt_coef(results["M2"], "ln_brent"),
            fmt_se(results["M2"], "ln_brent"),
            "—",
            "—",
            fmt_coef(results["M4"], "ln_brent"),
            fmt_se(results["M4"], "ln_brent"),
            fmt_coef(results["M5"], "ln_brent"),
            fmt_se(results["M5"], "ln_brent"),
        ],
        [
            "ln人口",
            "",
            fmt_coef(results["M1"], "ln_population"),
            fmt_se(results["M1"], "ln_population"),
            fmt_coef(results["M2"], "ln_population"),
            fmt_se(results["M2"], "ln_population"),
            fmt_coef(results["M3"], "ln_population"),
            fmt_se(results["M3"], "ln_population"),
            fmt_coef(results["M4"], "ln_population"),
            fmt_se(results["M4"], "ln_population"),
            fmt_coef(results["M5"], "ln_population"),
            fmt_se(results["M5"], "ln_population"),
        ],
        [
            INFRA_LABEL_CN,
            "",
            "—",
            "—",
            fmt_coef(results["M2"], INFRA_VAR),
            fmt_se(results["M2"], INFRA_VAR),
            fmt_coef(results["M3"], INFRA_VAR),
            fmt_se(results["M3"], INFRA_VAR),
            fmt_coef(results["M4"], INFRA_VAR),
            fmt_se(results["M4"], INFRA_VAR),
            fmt_coef(results["M5"], INFRA_VAR),
            fmt_se(results["M5"], INFRA_VAR),
        ],
        ["样本量 N", "", int(results["M1"].nobs), "", int(results["M2"].nobs), "", int(results["M3"].nobs), "", int(results["M4"].nobs), "", int(results["M5"].nobs), ""],
        [
            "R²(within)",
            "",
            f"{results['M1'].rsquared_within:.3f}",
            "",
            f"{results['M2'].rsquared_within:.3f}",
            "",
            f"{results['M3'].rsquared_within:.3f}",
            "",
            f"{results['M4'].rsquared_within:.3f}",
            "",
            f"{results['M5'].rsquared_within:.3f}",
            "",
        ],
        ["国家固定效应", "", "✓", "", "✓", "", "✓", "", "✓", "", "✓", ""],
        ["时间固定效应", "", "", "", "", "", "✓", "", "", "", "", ""],
    ]
    pd.DataFrame(main_rows).to_csv(OUT_MAIN, index=False, header=False, encoding="utf-8-sig")

    het_rows = [
        ["变量", "", "高收入国", "", "非高收入国", ""],
        [
            "ln人均GDP",
            "",
            fmt_coef(results["M6_HIC"], "ln_gdp_pc_ppp"),
            fmt_se(results["M6_HIC"], "ln_gdp_pc_ppp"),
            fmt_coef(results["M7_nonHIC"], "ln_gdp_pc_ppp"),
            fmt_se(results["M7_nonHIC"], "ln_gdp_pc_ppp"),
        ],
        [
            "ln Brent油价",
            "",
            fmt_coef(results["M6_HIC"], "ln_brent"),
            fmt_se(results["M6_HIC"], "ln_brent"),
            fmt_coef(results["M7_nonHIC"], "ln_brent"),
            fmt_se(results["M7_nonHIC"], "ln_brent"),
        ],
        [
            "ln人口",
            "",
            fmt_coef(results["M6_HIC"], "ln_population"),
            fmt_se(results["M6_HIC"], "ln_population"),
            fmt_coef(results["M7_nonHIC"], "ln_population"),
            fmt_se(results["M7_nonHIC"], "ln_population"),
        ],
        [
            INFRA_LABEL_CN,
            "",
            fmt_coef(results["M6_HIC"], INFRA_VAR),
            fmt_se(results["M6_HIC"], INFRA_VAR),
            fmt_coef(results["M7_nonHIC"], INFRA_VAR),
            fmt_se(results["M7_nonHIC"], INFRA_VAR),
        ],
        ["样本量 N", "", int(results["M6_HIC"].nobs), "", int(results["M7_nonHIC"].nobs), ""],
        ["国家数", "", int(d_hic["iso3c"].nunique()), "", int(d_non["iso3c"].nunique()), ""],
        ["R²(within)", "", f"{results['M6_HIC'].rsquared_within:.3f}", "", f"{results['M7_nonHIC'].rsquared_within:.3f}", ""],
    ]
    pd.DataFrame(het_rows).to_csv(OUT_HET, index=False, header=False, encoding="utf-8-sig")


def save_descriptive_stats(panel_model: pd.DataFrame):
    cols = {
        "ev_sales_share_cars": "EV乘用车销售占比(%)",
        "ev_stock_share_cars": "EV乘用车保有占比(%)",
        "gdp_pc_ppp": "人均GDP PPP(美元)",
        "population": "人口(人)",
        "brent_usd": "Brent油价(美元/桶)",
        "chargers_total": "充电桩总数(个)",
        "chargers_per_mn": "充电桩密度(个/百万人)",
        "chargers_per_mn_itp": "充电桩密度(线性插值后,个/百万人)",
        "ln_charger_density_itp": "ln(充电桩密度,插值后)",
        "chargers_growth": "充电桩年增长率",
    }
    d = panel_model[list(cols.keys())].describe(percentiles=[0.25, 0.5, 0.75]).T
    d = d.rename(columns={"count": "观测数", "mean": "均值", "std": "标准差", "min": "最小值", "25%": "25%分位", "50%": "中位数", "75%": "75%分位", "max": "最大值"})
    d.index = [cols[i] for i in d.index]
    d.to_csv(OUT_DESC, encoding="utf-8-sig")


def save_dictionary():
    rows = [
        ["iso3c", "国家ISO3代码", "—", "IEA/WB", "国家标识", "字符型"],
        ["country", "国家名称", "—", "World Bank", "国家标识", "字符型"],
        ["year", "年份", "年", "—", "时间标识", "整数"],
        ["income_group", "WB收入分组", "—", "World Bank", "异质性分组(HIC/UMC/LMC)", "字符型"],
        ["ev_sales_share_cars", "EV乘用车销售占比【因变量】", "%", "IEA Global EV Outlook 2025", "新售车辆中EV比例", "(+)"],
        ["ev_stock_share_cars", "EV乘用车保有占比【稳健性因变量】", "%", "IEA Global EV Outlook 2025", "在用车辆中EV比例", "(+)"],
        ["gdp_pc_ppp", "人均GDP(PPP购买力平价)", "国际美元", "World Bank API (NY.GDP.PCAP.PP.CD)", "居民购买力", "(+)"],
        ["ln_gdp_pc_ppp", "ln(人均GDP)", "自然对数", "推导", "平滑化", "(+)"],
        ["population", "人口总数", "人", "World Bank API (SP.POP.TOTL)", "市场规模", "(±)"],
        ["ln_population", "ln(人口)", "自然对数", "推导", "平滑化", "(±)"],
        ["brent_usd", "Brent原油年均价", "美元/桶", "EIA", "燃油车运行成本代理", "(+)"],
        ["ln_brent", "ln(Brent油价)", "自然对数", "推导", "平滑化", "(+)"],
        ["chargers_total", "公用充电桩总数", "个", "IEA Global EV Outlook 2025", "快充+慢充", "(+)"],
        ["chargers_per_mn", "充电桩密度(每百万人)", "个/百万人", "推导", "基础设施水平", "(+)"],
        [INFRA_VAR, "充电桩密度(线性插值后)【主解释变量】", "个/百万人", "推导", "用于缓解偶发缺失并刻画基础设施完善度", "(+)"],
        ["chargers_growth", "充电桩年增长率", "比例", "推导", "建设速度", "(+)"],
        ["chargers_growth_lag1", "充电桩增长率(滞后1期)", "比例", "推导", "用于稳健性/机制扩展", "(±)"],
    ]
    pd.DataFrame(rows, columns=["变量名", "含义", "单位", "数据来源", "说明", "预期符号"]).to_csv(
        OUT_DICT, index=False, encoding="utf-8-sig"
    )


def save_coverage_metrics(panel_context: pd.DataFrame, panel_model: pd.DataFrame):
    metrics = []
    for col in [
        "ev_sales_share_cars",
        "ev_stock_share_cars",
        "chargers_total",
        "chargers_per_mn",
        "chargers_per_mn_itp",
        "ln_charger_density_itp",
        "chargers_growth",
        "chargers_growth_lag1",
        "gdp_pc_ppp",
        "population",
        "brent_usd",
        "income_group",
    ]:
        metrics.append(
            {
                "variable": col,
                "rows_model_window": len(panel_model),
                "missing_model_window": int(panel_model[col].isna().sum()),
                "coverage_rate_model_window": float(1 - panel_model[col].isna().mean()),
            }
        )
    extra = [
        {"variable": "countries", "rows_model_window": panel_model["iso3c"].nunique(), "missing_model_window": 0, "coverage_rate_model_window": 1.0},
        {"variable": "rows_context_window", "rows_model_window": len(panel_context), "missing_model_window": 0, "coverage_rate_model_window": 1.0},
    ]
    pd.DataFrame(metrics + extra).to_csv(OUT_METRICS, index=False, encoding="utf-8-sig")


def save_figures(panel_model: pd.DataFrame, sample_main: pd.DataFrame, results):
    plt.style.use("seaborn-v0_8-whitegrid")

    # Fig1: top 10 countries by 2024 EV share
    y24 = panel_model[panel_model["year"] == YEAR_MODEL_END][["iso3c", "ev_sales_share_cars"]].dropna()
    top = set(y24.nlargest(10, "ev_sales_share_cars")["iso3c"].tolist())
    p1 = panel_model[panel_model["iso3c"].isin(top)].copy()
    fig, ax = plt.subplots(figsize=(10, 5.6))
    for k, g in p1.groupby("iso3c"):
        ax.plot(g["year"], g["ev_sales_share_cars"], label=k, linewidth=1.8)
    ax.set_xlabel("Year")
    ax.set_ylabel("EV sales share (%)")
    ax.set_title("EV penetration trends across selected countries")
    ax.legend(ncol=2, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(FIG1, dpi=300)
    plt.close(fig)

    # Fig2: 2024 scatter GDP vs EV sales share
    p2 = panel_model[panel_model["year"] == YEAR_MODEL_END].dropna(subset=["gdp_pc_ppp", "ev_sales_share_cars"])
    color_map = {"HIC": "#1f77b4", "UMC": "#ff7f0e", "LMC": "#2ca02c"}
    fig, ax = plt.subplots(figsize=(7.8, 5.6))
    for ig, g in p2.groupby("income_group"):
        ax.scatter(g["gdp_pc_ppp"], g["ev_sales_share_cars"], s=35, alpha=0.8, label=ig, color=color_map.get(ig, "#777777"))
    ax.set_xscale("log")
    ax.set_xlabel("GDP per capita, PPP (log scale)")
    ax.set_ylabel("EV sales share (%)")
    ax.set_title("GDP per capita vs EV penetration (2024)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG2, dpi=300)
    plt.close(fig)

    # Fig3: charger density vs EV sales share (same style, updated variable)
    p3 = sample_main.dropna(subset=[INFRA_VAR, "ev_sales_share_cars"])
    fig, ax = plt.subplots(figsize=(7.8, 5.6))
    ax.scatter(p3[INFRA_VAR], p3["ev_sales_share_cars"], s=18, alpha=0.65, color="#4c78a8")
    if len(p3) > 10:
        z = np.polyfit(p3[INFRA_VAR], p3["ev_sales_share_cars"], 1)
        xs = np.linspace(p3[INFRA_VAR].min(), p3[INFRA_VAR].max(), 200)
        ys = z[0] * xs + z[1]
        ax.plot(xs, ys, color="#d62728", linewidth=2)
        ax.text(
            0.03,
            0.95,
            f"y = {z[0]:.4f}x + {z[1]:.2f}",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            bbox=dict(facecolor="white", alpha=0.7, edgecolor="none"),
        )
    ax.set_xlabel("Charger density per million people (interpolated)")
    ax.set_ylabel("EV sales share (%)")
    ax.set_title("Charger density and EV penetration")
    fig.tight_layout()
    fig.savefig(FIG3, dpi=300)
    plt.close(fig)

    # Fig4: focused heterogeneity figure for charger density only
    hic_coef = results["M6_HIC"].params[INFRA_VAR]
    hic_err = 1.96 * results["M6_HIC"].std_errors[INFRA_VAR]
    non_coef = results["M7_nonHIC"].params[INFRA_VAR]
    non_err = 1.96 * results["M7_nonHIC"].std_errors[INFRA_VAR]

    fig, ax = plt.subplots(figsize=(7.0, 5.0))
    x = np.array([0, 1])
    y = np.array([hic_coef, non_coef])
    yerr = np.array([hic_err, non_err])
    ax.bar(x, y, width=0.55, yerr=yerr, capsize=5, color=["#d62728", "#1f77b4"], alpha=0.9)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(["HIC", "Non-HIC"])
    ax.set_ylim(0, 0.025)
    ax.set_ylabel("Coefficient on charger density (per million)")
    ax.set_title("Heterogeneity in charger-density effect (95% CI)")
    for xi, yi in zip(x, y):
        ax.text(xi, yi + 0.0007, f"{yi:.3f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG4, dpi=300)
    plt.close(fig)


def save_density_form_robustness(panel_model: pd.DataFrame):
    rows = []
    for var, label in [("chargers_per_mn_itp", "level_density"), ("ln_charger_density_itp", "log_density")]:
        d = panel_model.dropna(
            subset=["ev_sales_share_cars", "ln_gdp_pc_ppp", "ln_brent", "ln_population", var]
        ).set_index(["iso3c", "year"])
        m2 = PanelOLS(
            d["ev_sales_share_cars"], d[["ln_gdp_pc_ppp", "ln_brent", "ln_population", var]], entity_effects=True
        ).fit(cov_type="clustered", cluster_entity=True)
        m3 = PanelOLS(
            d["ev_sales_share_cars"], d[["ln_gdp_pc_ppp", "ln_population", var]], entity_effects=True, time_effects=True, drop_absorbed=True
        ).fit(cov_type="clustered", cluster_entity=True)
        rows.append(
            {
                "spec": label,
                "var": var,
                "coef_M2": m2.params[var],
                "p_M2": m2.pvalues[var],
                "coef_M3": m3.params[var],
                "p_M3": m3.pvalues[var],
                "N": int(m2.nobs),
            }
        )
    pd.DataFrame(rows).to_csv(OUT_DENSITY_FORM, index=False, encoding="utf-8-sig")


def main():
    # 1) Build panel pieces
    iea_panel = build_iea_panel()
    iso3_list = sorted(iea_panel["iso3c"].dropna().unique().tolist())
    wb_panel = load_wb_with_fallback(iso3_list)
    brent = load_brent()

    # 2) Merge
    panel = iea_panel.merge(wb_panel, on=["iso3c", "year"], how="left")
    panel = panel.merge(brent, on="year", how="left")
    panel = panel.sort_values(["iso3c", "year"]).reset_index(drop=True)

    # 3) Derived variables on context window (critical for 2015 lag availability)
    panel["chargers_per_mn"] = panel["chargers_total"] / (panel["population"] / 1e6)
    panel["chargers_per_mn_itp"] = panel.groupby("iso3c", dropna=False)["chargers_per_mn"].transform(
        lambda s: s.interpolate(method="linear", limit=2, limit_direction="both")
    )
    panel["ln_gdp_pc_ppp"] = np.log(panel["gdp_pc_ppp"])
    panel["ln_population"] = np.log(panel["population"])
    panel["ln_brent"] = np.log(panel["brent_usd"])
    panel["ln_chargers_per_mn"] = np.log(panel["chargers_per_mn"].replace(0, np.nan))
    panel["ln_charger_density_itp"] = np.log(panel["chargers_per_mn_itp"].replace(0, np.nan))

    g = panel.groupby("iso3c", dropna=False)["chargers_total"]
    prev = g.shift(1)
    panel["chargers_growth"] = np.where((panel["chargers_total"].notna()) & (prev > 0), panel["chargers_total"] / prev - 1, np.nan)
    panel["chargers_growth_lag1"] = panel.groupby("iso3c", dropna=False)["chargers_growth"].shift(1)

    panel_context = panel[(panel["year"] >= YEAR_CONTEXT_START) & (panel["year"] <= YEAR_CONTEXT_END)].copy()
    panel_model = panel[(panel["year"] >= YEAR_MODEL_START) & (panel["year"] <= YEAR_MODEL_END)].copy()

    # 4) Save panel and main regression sample
    panel_model.to_csv(OUT_PANEL, index=False, encoding="utf-8-sig")
    sample_main = panel_model.dropna(
        subset=["ev_sales_share_cars", "ln_gdp_pc_ppp", "ln_brent", "ln_population", INFRA_VAR]
    ).copy()
    sample_main.to_csv(OUT_SAMPLE, index=False, encoding="utf-8-sig")

    # 5) Regressions + tables
    results, sample_main_idx, d_hic, d_non = run_panel_models(panel_model)
    save_regression_tables(results, d_hic, d_non)
    save_descriptive_stats(panel_model)
    save_dictionary()
    save_coverage_metrics(panel_context, panel_model)
    save_density_form_robustness(panel_model)

    # 6) Figures
    save_figures(panel_model, sample_main_idx, results)

    # 7) Console summary
    print(f"[OK] Panel rows (2015-2024): {len(panel_model)}, countries: {panel_model['iso3c'].nunique()}")
    print(f"[OK] Main regression sample N: {int(results['M2'].nobs)}")
    y2015 = panel_model[panel_model["year"] == 2015]
    print(f"[OK] 2015 rows with charger density(itp): {int(y2015[INFRA_VAR].notna().sum())}")
    print(f"[OK] Coef M2 ln_gdp_pc_ppp: {results['M2'].params['ln_gdp_pc_ppp']:.3f}")
    print(f"[OK] Coef M2 {INFRA_VAR}: {results['M2'].params[INFRA_VAR]:.3f}")


if __name__ == "__main__":
    main()

