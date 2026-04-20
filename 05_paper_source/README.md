# 交付说明 / Handoff

**项目**:跨国视角下新能源汽车渗透率影响因素与驱动机制研究
**数据处理:** tu
**生成日期:** 2026-04-18

## 文件清单

### 数据
- `panel_final.csv` — 最终面板数据,53国×10年(2015-2024),501行,UTF-8 BOM
- `regression_sample_main.csv` — 主回归使用的子样本(含充电桩密度插值变量,N=346)
- `variable_dictionary.csv` — 变量字典(含单位、来源、预期符号)
- `descriptive_stats.csv` — 关键变量描述统计

### 结果
- `regression_main.csv` — 主回归表(M1-M5,便于粘到Word里)
- `regression_heterogeneity.csv` — 异质性分析表(高收入 vs 非高收入)
- `density_form_robustness.csv` — 充电桩“水平密度 vs 对数密度”形式稳健性对比

### 图
- `fig1_ev_penetration_trend.png` — 10国EV渗透率时间趋势
- `fig2_gdp_vs_penetration.png` — GDP与渗透率散点(2024年,按收入分组)
- `fig3_chargers_vs_ev.png` — 充电桩密度与EV渗透率散点
- `fig4_heterogeneity.png` — 充电桩密度异质性对比柱状图(HIC vs 非HIC)

### 脚本
- `analysis_refresh.py` — 完整可复现脚本（自动通过 wbgapi 拉取WB数据）

### 原始数据依赖(放同目录即可重跑)
- `EVDataExplorer2025(4).xlsx`
- `wb_gdp.csv`(PowerShell拉取,见METHODOLOGY.md)
- `wb_pop.csv`(同上)
- `Europe_Brent_Spot_Price_FOB.csv`

## 主要结论(供论文写作参考)

1. **人均GDP是EV渗透率的核心驱动因素**:ln(人均GDP)系数在主模型为30.253***,
   1%水平显著。居民购买力每提升1%,EV销售占比上升约0.303个百分点。

2. **充电基础设施水平呈现显著正向作用**:将核心变量改为“每百万人充电桩密度”
   并对短缺口(最多2年)做线性插值后,主模型中系数约0.004***。即充电桩密度每增加
   100个/百万人,EV销售占比约提升0.4个百分点。

3. **异质性显著**:充电桩密度系数在高收入国家与非高收入国家均显著为正,
   且非高收入国家边际效应更高(约0.017*** vs 0.003**)。

4. **油价效应在主模型中不稳定**:ln(Brent油价)在加入时间固定效应后被吸收，
   在单向固定效应模型中也未表现出稳健显著性。

## 重要说明 - 论文写作时必读

### 1. 关于政策变量与电价
原方案拟纳入政策打分(subsidy/tax/road/infra)与各国电价做机制回归,但:
- 政策变量搜集同学提供的CSV仅有表头,无实际数据
- 分国电价数据同样缺失(欧盟gz文件实际是SDMX元数据,非数据本身)

因此本文未纳入这两类变量。论文讨论部分应坦诚说明,
并列为未来研究方向。**不建议**基于PDF人工"编造"打分,会有
复现审查风险(大赛要求数据包可复现)。

### 2. 油价符号异常
不要强行把负号解释成正。应:
- 客观呈现结果
- 在讨论部分给出两种可能解释(见主要结论第4点)
- 这不会失分,反而体现研究诚实

### 3. 充电桩采用“密度水平”作为主解释变量
论文中需说明:
- 为什么用充电桩密度(chargers\_per\_mn\_itp)而不是增长率(chargers\_growth\_lag1)
- 原因:增长率在低基数国家极端波动,容易扭曲跨国比较;密度更能反映基建完善度
- 缺失处理:对每国最多2年的短缺口做线性插值,提升样本代表性

### 4. WB收入分组
基于世界银行2023年标准。HIC=高收入(39国),UMC=中高(11国),LMC=中低(3国)。
因LMC样本过小,异质性做高收入vs非高收入二分。

## 时间窗口

2015-2024,共10年。本可以做到2015-2025,但Brent油价2025年数据仅涵盖1-3月,
剔除。

## 样本国家

53个,去除了IEA中的地区聚合(如"EU27"、"World"、"Europe"等)。
具体列表见`panel_final.csv`的`iso3c`列。

## 如需复现

```bash
pip install pandas numpy openpyxl wbgapi linearmodels matplotlib
python analysis_refresh.py
```

原始数据中,`wb_gdp.csv`和`wb_pop.csv`需用PowerShell从World Bank API拉取,
命令见METHODOLOGY.md。搜数据同学原始提供的WB文件遗漏了14个国家,
故重拉了完整版。
