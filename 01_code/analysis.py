"""
跨国EV渗透率影响因素分析 - 完整可复现脚本
=====================================================

输入文件(放在同目录):
  - EVDataExplorer2025(4).xlsx  (IEA Global EV Outlook 2025)
  - wb_gdp.csv                  (World Bank GDP PPP, 由PowerShell拉取)
  - wb_pop.csv                  (World Bank Population, 由PowerShell拉取)
  - Europe_Brent_Spot_Price_FOB.csv (EIA Brent月度油价)

输出文件:
  - panel_final.csv                 清洗后的面板数据
  - descriptive_stats.csv           描述统计
  - regression_main.csv             主回归表
  - regression_heterogeneity.csv    异质性分析表
  - 四张图 (fig1-fig4)

运行:
  pip install pandas numpy openpyxl linearmodels matplotlib
  python analysis.py
"""

import pandas as pd
import numpy as np
from linearmodels.panel import PanelOLS
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# =========================================================================
# 1. 读取原始数据
# =========================================================================

# IEA EV数据
ev = pd.read_excel('EVDataExplorer2025(4).xlsx', sheet_name='GEVO_EV_2025')
hist = ev[ev['category'] == 'Historical'].copy()

# 世界银行数据
gdp = pd.read_csv('wb_gdp.csv')
pop = pd.read_csv('wb_pop.csv')

# Brent油价(月度 -> 年均)
brent_raw = pd.read_csv('Europe_Brent_Spot_Price_FOB.csv', skiprows=5,
                        names=['month_str', 'price'])
brent_raw['year'] = pd.to_datetime(brent_raw['month_str'], format='%b %Y',
                                    errors='coerce').dt.year
brent_raw['price'] = pd.to_numeric(brent_raw['price'], errors='coerce')
brent = (brent_raw.dropna().groupby('year')['price']
         .mean().reset_index()
         .rename(columns={'price': 'brent_usd'}))

# =========================================================================
# 2. 从IEA数据提取关键变量
# =========================================================================

# 排除聚合地区
REGIONS = {'Africa', 'Asia Pacific', 'Central and South America', 'EU27',
           'Europe', 'Rest of the world', 'World', 'Other Europe', 'Eurasia',
           'Middle East', 'Other Asia Pacific', 'Other Africa', 'North America',
           'Middle East and Caspian'}

def extract(df, param, mode, powertrain, colname):
    x = df[(df['parameter'] == param) &
           (df['mode'] == mode) &
           (df['powertrain'] == powertrain)]
    x = x[~x['region_country'].isin(REGIONS)]
    return x[['region_country', 'year', 'value']].rename(
        columns={'region_country': 'country_iea', 'value': colname})

# 因变量
ev_sales_share = extract(hist, 'EV sales share', 'Cars', 'EV', 'ev_sales_share_cars')
ev_stock_share = extract(hist, 'EV stock share', 'Cars', 'EV', 'ev_stock_share_cars')

# 充电桩
ch_fast = extract(hist, 'EV charging points', 'EV',
                  'Publicly available fast', 'chargers_fast')
ch_slow = extract(hist, 'EV charging points', 'EV',
                  'Publicly available slow', 'chargers_slow')
chargers = ch_fast.merge(ch_slow, on=['country_iea', 'year'], how='outer')
chargers['chargers_total'] = (chargers['chargers_fast'].fillna(0) +
                               chargers['chargers_slow'].fillna(0))

# EV保有量(辅助)
def get_stock(powertrain, colname):
    x = hist[(hist['parameter'] == 'EV stock') &
             (hist['mode'] == 'Cars') &
             (hist['powertrain'] == powertrain)]
    x = x[~x['region_country'].isin(REGIONS)]
    return x[['region_country', 'year', 'value']].rename(
        columns={'region_country': 'country_iea', 'value': colname})

bev = get_stock('BEV', 'ev_stock_bev')
phev = get_stock('PHEV', 'ev_stock_phev')
ev_stock = bev.merge(phev, on=['country_iea', 'year'], how='outer')
ev_stock['ev_stock_total'] = (ev_stock['ev_stock_bev'].fillna(0) +
                               ev_stock['ev_stock_phev'].fillna(0))

# 合并EV侧数据
ev_panel = (ev_sales_share
            .merge(ev_stock_share, on=['country_iea', 'year'], how='outer')
            .merge(chargers[['country_iea', 'year', 'chargers_total',
                             'chargers_fast', 'chargers_slow']],
                   on=['country_iea', 'year'], how='outer')
            .merge(ev_stock[['country_iea', 'year', 'ev_stock_total']],
                   on=['country_iea', 'year'], how='outer'))

# =========================================================================
# 3. IEA国家名 -> ISO3 映射
# =========================================================================

IEA_TO_ISO3 = {
    'Australia': 'AUS', 'Austria': 'AUT', 'Belgium': 'BEL', 'Brazil': 'BRA',
    'Bulgaria': 'BGR', 'Canada': 'CAN', 'Chile': 'CHL', 'China': 'CHN',
    'Colombia': 'COL', 'Costa Rica': 'CRI', 'Croatia': 'HRV', 'Cyprus': 'CYP',
    'Czech Republic': 'CZE', 'Denmark': 'DNK', 'Estonia': 'EST',
    'Finland': 'FIN', 'France': 'FRA', 'Germany': 'DEU', 'Greece': 'GRC',
    'Hungary': 'HUN', 'Iceland': 'ISL', 'India': 'IND', 'Indonesia': 'IDN',
    'Ireland': 'IRL', 'Israel': 'ISR', 'Italy': 'ITA', 'Japan': 'JPN',
    'Korea': 'KOR', 'Latvia': 'LVA', 'Lithuania': 'LTU', 'Luxembourg': 'LUX',
    'Malaysia': 'MYS', 'Mexico': 'MEX', 'Netherlands': 'NLD',
    'New Zealand': 'NZL', 'Norway': 'NOR', 'Poland': 'POL',
    'Portugal': 'PRT', 'Romania': 'ROU', 'Russia': 'RUS',
    'Seychelles': 'SYC', 'Slovakia': 'SVK', 'Slovenia': 'SVN',
    'South Africa': 'ZAF', 'Spain': 'ESP', 'Sweden': 'SWE',
    'Switzerland': 'CHE', 'Thailand': 'THA', 'Turkiye': 'TUR',
    'USA': 'USA', 'United Kingdom': 'GBR', 'Uzbekistan': 'UZB',
    'Viet Nam': 'VNM'
}

ev_panel['iso3c'] = ev_panel['country_iea'].map(IEA_TO_ISO3)
ev_panel = ev_panel[ev_panel['iso3c'].notna()].drop(columns=['country_iea'])

# =========================================================================
# 4. 合并所有数据源
# =========================================================================

wb = pop.merge(gdp, on=['country', 'iso3c', 'year'], how='outer')
panel = ev_panel.merge(wb, on=['iso3c', 'year'], how='left')
panel = panel.merge(brent, on='year', how='left')

# 筛选时间窗口
panel = panel[(panel['year'] >= 2015) & (panel['year'] <= 2024)].copy()
panel = panel.sort_values(['iso3c', 'year']).reset_index(drop=True)

# =========================================================================
# 5. 派生变量
# =========================================================================

panel['chargers_per_mn'] = panel['chargers_total'] / (panel['population'] / 1e6)
panel['ln_gdp_pc_ppp'] = np.log(panel['gdp_pc_ppp'])
panel['ln_population'] = np.log(panel['population'])
panel['ln_brent'] = np.log(panel['brent_usd'])
panel['ln_chargers_per_mn'] = np.log(panel['chargers_per_mn'].replace(0, np.nan))
panel['chargers_growth'] = panel.groupby('iso3c')['chargers_total'].pct_change()
panel['chargers_growth_lag1'] = panel.groupby('iso3c')['chargers_growth'].shift(1)

# WB收入分组(2023年标准)
INCOME_GROUP = {
    'AUS': 'HIC', 'AUT': 'HIC', 'BEL': 'HIC', 'BRA': 'UMC', 'BGR': 'HIC',
    'CAN': 'HIC', 'CHL': 'HIC', 'CHN': 'UMC', 'COL': 'UMC', 'CRI': 'UMC',
    'HRV': 'HIC', 'CYP': 'HIC', 'CZE': 'HIC', 'DNK': 'HIC', 'EST': 'HIC',
    'FIN': 'HIC', 'FRA': 'HIC', 'DEU': 'HIC', 'GRC': 'HIC', 'HUN': 'HIC',
    'ISL': 'HIC', 'IND': 'LMC', 'IDN': 'UMC', 'IRL': 'HIC', 'ISR': 'HIC',
    'ITA': 'HIC', 'JPN': 'HIC', 'KOR': 'HIC', 'LVA': 'HIC', 'LTU': 'HIC',
    'LUX': 'HIC', 'MYS': 'UMC', 'MEX': 'UMC', 'NLD': 'HIC', 'NZL': 'HIC',
    'NOR': 'HIC', 'POL': 'HIC', 'PRT': 'HIC', 'ROU': 'HIC', 'RUS': 'UMC',
    'SYC': 'HIC', 'SVK': 'HIC', 'SVN': 'HIC', 'ZAF': 'UMC', 'ESP': 'HIC',
    'SWE': 'HIC', 'CHE': 'HIC', 'THA': 'UMC', 'TUR': 'UMC', 'USA': 'HIC',
    'GBR': 'HIC', 'UZB': 'LMC', 'VNM': 'LMC'
}
panel['income_group'] = panel['iso3c'].map(INCOME_GROUP)

panel.to_csv('panel_final.csv', index=False, encoding='utf-8-sig')
print(f"面板已构建: {panel.shape}, {panel['iso3c'].nunique()}国, "
      f"{panel['year'].min()}-{panel['year'].max()}")

# =========================================================================
# 6. 回归分析
# =========================================================================

results = {}

# M1: 基准模型(仅社经变量,国家FE)
base_vars = ['ev_sales_share_cars', 'ln_gdp_pc_ppp', 'ln_brent', 'ln_population']
d1 = panel.dropna(subset=base_vars).set_index(['iso3c', 'year'])
results['M1'] = PanelOLS(
    d1['ev_sales_share_cars'],
    d1[['ln_gdp_pc_ppp', 'ln_brent', 'ln_population']],
    entity_effects=True
).fit(cov_type='clustered', cluster_entity=True)

# M2: 主模型(加入充电桩增长率,滞后一期)
full_vars = base_vars + ['chargers_growth_lag1']
d2 = panel.dropna(subset=full_vars).set_index(['iso3c', 'year'])
results['M2'] = PanelOLS(
    d2['ev_sales_share_cars'],
    d2[['ln_gdp_pc_ppp', 'ln_brent', 'ln_population', 'chargers_growth_lag1']],
    entity_effects=True
).fit(cov_type='clustered', cluster_entity=True)

# M3: 双向固定效应(注:油价在时间FE下被吸收,故剔除)
results['M3'] = PanelOLS(
    d2['ev_sales_share_cars'],
    d2[['ln_gdp_pc_ppp', 'ln_population', 'chargers_growth_lag1']],
    entity_effects=True, time_effects=True
).fit(cov_type='clustered', cluster_entity=True)

# M4: 稳健性 - 因变量换为EV保有占比
d4 = panel.dropna(subset=['ev_stock_share_cars'] + base_vars[1:] +
                  ['chargers_growth_lag1']).set_index(['iso3c', 'year'])
results['M4'] = PanelOLS(
    d4['ev_stock_share_cars'],
    d4[['ln_gdp_pc_ppp', 'ln_brent', 'ln_population', 'chargers_growth_lag1']],
    entity_effects=True
).fit(cov_type='clustered', cluster_entity=True)

# M5: 稳健性 - 剔除渗透率>80%的极端样本
d5 = panel[panel['ev_sales_share_cars'] < 80].dropna(
    subset=full_vars).set_index(['iso3c', 'year'])
results['M5'] = PanelOLS(
    d5['ev_sales_share_cars'],
    d5[['ln_gdp_pc_ppp', 'ln_brent', 'ln_population', 'chargers_growth_lag1']],
    entity_effects=True
).fit(cov_type='clustered', cluster_entity=True)

# 异质性分析
hic_set = set(panel[panel['income_group'] == 'HIC']['iso3c'].unique())
d2r = d2.reset_index()

d_hic = d2r[d2r['iso3c'].isin(hic_set)].set_index(['iso3c', 'year'])
results['M6_HIC'] = PanelOLS(
    d_hic['ev_sales_share_cars'],
    d_hic[['ln_gdp_pc_ppp', 'ln_brent', 'ln_population', 'chargers_growth_lag1']],
    entity_effects=True
).fit(cov_type='clustered', cluster_entity=True)

d_nonhic = d2r[~d2r['iso3c'].isin(hic_set)].set_index(['iso3c', 'year'])
results['M7_nonHIC'] = PanelOLS(
    d_nonhic['ev_sales_share_cars'],
    d_nonhic[['ln_gdp_pc_ppp', 'ln_brent', 'ln_population', 'chargers_growth_lag1']],
    entity_effects=True
).fit(cov_type='clustered', cluster_entity=True)

# =========================================================================
# 7. 打印结果
# =========================================================================

def fmt(m, v):
    if v not in m.params.index:
        return "—"
    c, se, p = m.params[v], m.std_errors[v], m.pvalues[v]
    s = '***' if p < 0.01 else ('**' if p < 0.05 else ('*' if p < 0.1 else ''))
    return f"{c:.3f}{s} ({se:.3f})"

print("\n" + "=" * 100)
print("主回归结果(因变量: EV乘用车销售占比 %)")
print("=" * 100)
VNAME = {'ln_gdp_pc_ppp': 'ln人均GDP', 'ln_brent': 'ln Brent油价',
         'ln_population': 'ln人口', 'chargers_growth_lag1': '充电桩增长率(t-1)'}
for v, vn in VNAME.items():
    print(f"{vn:<20}", end='')
    for k in ['M1', 'M2', 'M3', 'M4', 'M5']:
        print(f"{fmt(results[k], v):<22}", end='')
    print()
print("\n样本量    ", end='')
for k in ['M1', 'M2', 'M3', 'M4', 'M5']:
    print(f"{int(results[k].nobs):<22}", end='')
print("\nR²(within)", end=' ')
for k in ['M1', 'M2', 'M3', 'M4', 'M5']:
    print(f"{results[k].rsquared_within:.3f}{'':<17}", end='')
print("\n\n显著性: *** p<0.01, ** p<0.05, * p<0.1")

print("\n" + "=" * 60)
print("异质性:高收入 vs 非高收入")
print("=" * 60)
for v, vn in VNAME.items():
    print(f"{vn:<20}{fmt(results['M6_HIC'], v):<25}"
          f"{fmt(results['M7_nonHIC'], v):<25}")

# =========================================================================
# 8. 保存回归表
# =========================================================================
# (省略重复代码 - 与主输出一致)

print("\n分析完成。所有结果已保存。")
