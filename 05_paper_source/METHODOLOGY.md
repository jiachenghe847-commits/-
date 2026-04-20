# 数据与方法 (METHODOLOGY)

## 一、数据来源

| 数据集 | 原始来源 | 覆盖范围 | 本研究使用 |
|---|---|---|---|
| EV销售占比、保有占比 | IEA Global EV Outlook 2025 | 全球63国,2010-2024 | 乘用车(Cars),动力类型合并(EV=BEV+PHEV) |
| 公用充电桩数 | IEA Global EV Outlook 2025 | 全球43国,2010-2024 | 快充+慢充合计 |
| EV保有量 | IEA Global EV Outlook 2025 | — | BEV+PHEV合计,构造辅助变量 |
| 人均GDP (PPP) | World Bank WDI (NY.GDP.PCAP.PP.CD) | 全球200+国,至2024 | 直接对数化 |
| 总人口 | World Bank WDI (SP.POP.TOTL) | 全球200+国,至2024 | 直接对数化 |
| Brent原油现货价 | U.S. EIA (via Thomson Reuters) | 全球统一,月度至2025 | 月度均值折算年均 |
| 收入分组 | World Bank 2023年分类 | — | HIC / UMC / LMC |

**时间窗口:** 2015-2024,共10年。
**最终样本:** 53个国家(剔除IEA中的聚合地区如EU27、Europe、World等)。
**主回归样本量:** 346观测(受充电桩数据可用性约束)。

## 二、变量构造

### 因变量
- **EV乘用车销售占比** (`ev_sales_share_cars`, %)
  IEA口径,新售乘用车中EV(BEV+PHEV)占比。
- **EV乘用车保有占比** (`ev_stock_share_cars`, %)
  在用乘用车中EV占比。用于稳健性检验。

### 核心解释变量
- **ln(人均GDP PPP)** (`ln_gdp_pc_ppp`)
  对购买力平价美元的人均GDP取自然对数。预期符号:(+)
- **ln(Brent油价)** (`ln_brent`)
  年均价自然对数。预期符号:(+)——理论上油价涨燃油车更贵,EV更吸引人。
- **ln(人口)** (`ln_population`)
  市场规模控制。国家固定效应下,该变量主要反映时间内增长。
- **充电桩密度(线性插值后)** (`chargers_per_mn_itp`)
  `chargers_total / (population/1e6)`，单位为“个/百万人”。
  对每国最多2年短缺口采用线性插值(`limit=2, limit_direction='both'`)以缓解样本流失。
  该变量在主回归中显著为正，且经济含义直观（基础设施水平越高，渗透率越高）。

### 控制 / 分组
- 国家固定效应:吸收时不变国家特征(文化、地理、初始禀赋等)
- 时间固定效应(仅M3):吸收全球共同冲击(疫情、供应链、技术进步等)
- 收入分组:用于异质性分析

## 三、计量模型

### 基准模型(单向固定效应)
$$y_{it} = \alpha_i + \beta_1 \ln\text{GDP}_{it} + \beta_2 \ln\text{Brent}_t + \beta_3 \ln\text{Pop}_{it} + \beta_4 \text{ChargerDensity}_{it} + \varepsilon_{it}$$

其中:
- $y_{it}$ = i国t年EV销售占比
- $\alpha_i$ = 国家固定效应
- $\varepsilon_{it}$ = 扰动项

### 双向固定效应(M3)
$$y_{it} = \alpha_i + \gamma_t + \beta_1 \ln\text{GDP}_{it} + \beta_3 \ln\text{Pop}_{it} + \beta_4 \text{ChargerDensity}_{it} + \varepsilon_{it}$$

**油价变量在时间FE下被完全吸收**(油价对所有国家同期一致,无国家间变异),
linearmodels自动检测并报错;故在M3中剔除该变量。

### 稳健标准误
所有模型使用**国家聚类稳健标准误**(cluster-entity),允许同一国家内不同年份扰动项相关。

## 四、稳健性与异质性

| 模型 | 设定 | 目的 |
|---|---|---|
| M1 | 仅社经变量 + 国家FE | 显示基准关系 |
| M2 | 加充电桩密度(插值) + 国家FE | 主回归 |
| M3 | M2 + 时间FE(去油价) | 检验时间共同冲击 |
| M4 | 因变量换为EV保有占比 | 因变量口径稳健性 |
| M5 | 剔除渗透率>80%的极端样本 | 检验挪威等领跑者影响 |
| M6 | 限定高收入国(HIC,27国) | 异质性 |
| M7 | 限定非高收入国(UMC+LMC,11国) | 异质性 |

## 五、数据处理的关键决策

### 1. 两个"空"文件的处理
搜集同学提供的`policy_country_year_scores.csv`与`energy_prices_country_year.csv`
仅含表头无数据。**选择不纳入**,而不是人为打分或用不完整的欧盟电价替代。
理由:
- 大赛要求数据包可复现,人工打分缺乏客观标准;
- 仅欧盟电价会把样本从53国砍到30国,牺牲代表性换不具有理论创新的机制回归,不划算;
- 论文讨论中坦诚说明,列为未来研究方向,在学术上完全站得住。

### 2. WB数据重新拉取
搜集同学的WB文件调用API时使用了`mrnev=500`参数,导致意外截断,
漏掉14个国家(主要为欧盟东部小国)。本研究通过PowerShell重新拉取完整数据:

```powershell
# GDP per capita PPP
$all = @()
for ($page = 1; $page -le 10; $page++) {
    $url = "https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.PP.CD?format=json&per_page=20000&page=$page&date=2015:2024"
    $r = Invoke-RestMethod -Uri $url
    if ($r.Count -lt 2 -or $null -eq $r[1]) { break }
    $all += $r[1]
    if ($page -ge $r[0].pages) { break }
}
$all | Where-Object { $_.value -ne $null -and $_.countryiso3code -ne "" } |
  Select-Object @{n='country';e={$_.country.value}}, @{n='iso3c';e={$_.countryiso3code}},
                @{n='year';e={$_.date}}, @{n='gdp_pc_ppp';e={$_.value}} |
  Export-Csv -Path wb_gdp.csv -NoTypeInformation -Encoding UTF8

# 人口类似(SP.POP.TOTL)
```

### 3. 充电桩数据合并
IEA数据中快充(fast)与慢充(slow)分列。合并时处理原则:
- 如某国某年仅有fast数据,chargers_slow视为0填充后相加
- 反之同理
- 两者都缺,则`chargers_total`缺失

## 六、局限与未来研究

1. **政策与电价变量缺失**:是本研究最大遗憾。理想情况下应纳入以识别机制。
2. **时间窗口较短**:10年面板,动态面板(如System GMM)数据量偏紧。
3. **EV定义**:采用IEA口径,含BEV+PHEV。未来可分拆分析。
4. **油价度量**:Brent为国际参考,未反映各国零售端汽油价差异。
5. **低收入国家样本仅3个**:异质性只能做HIC vs non-HIC,未能进一步细分。
