# Bullseye 量化交易框架

[![CI](https://github.com/lzy1102/bullseye/actions/workflows/ci.yml/badge.svg)](https://github.com/lzy1102/bullseye/actions/workflows/ci.yml)

[English](README.md) | **中文**

兼容 [Freqtrade](https://github.com/freqtrade/freqtrade) 策略接口的量化交易框架，
支持加密货币、A股股票与国内期货。

- 策略文档（逻辑/参数/收益全记录）：[`docs/strategies.md`](docs/strategies.md)
- 网关/实盘桥接开发标准：[`docs/gateway-development.md`](docs/gateway-development.md)
- 趋势判断方法基准测试：[`docs/trend-detection-benchmark.md`](docs/trend-detection-benchmark.md)

## 核心特性

- **100% 兼容 Freqtrade 策略接口** —— 现有 Freqtrade 策略直接可用
- **多市场支持**：
  - 加密货币（CCXT）：Binance、OKX、Bybit、Gate.io 等 100+ 交易所
  - A股（miniQMT/xtquant 或自建订单桥）：上交所/深交所/北交所
  - 期货（CTP/openctp-ctp）：国内六大期货交易所
  - 模拟盘（Dry Run）：真实行情 + 模拟成交
- **回测引擎**：
  - T+1/T+N 结算强制（A股当日买入不可卖，回测如实执行）
  - 逐日盯市净值曲线 + 曲线级回撤（捕捉持仓内回撤）
  - 手续费 + 不利滑点成交模型；结构化A股费率（佣金万2.5最低5元、印花税、过户费）
  - 向量化信号计算（长历史约1000倍提速）；支持内存数据 `run(data={...})`
  - **区间预热**：自动加载 timerange 之前的数据，SMA250/周线门禁等在首个交易日即有效
  - **`backtest.fill_next_open`**：可选的次日开盘成交语义（默认仍为当根收盘成交）
  - Baostock日线额外落盘流动性/估值因子列（`turn`/`peTTM`/`pbMRQ`/`psTTM`/`pcfNcfTTM`/`isST`）
- **@informative 多周期**：回测与实盘一致执行，防未来函数合并
- **超参优化**：随机搜索 + 多种损失函数
- **实盘链路**：订单执行器/仓位管理/钱包同步走网关；T+1可用量、整手、涨跌停规则内建
- **自定义网关**：`market_type: custom` 动态加载，配 HTTP 订单桥即可对接任意券商通道

## 策略组合与回测收益

参考策略位于 `user_data/strategies/`（同名 `{Strategy}.json` 参数文件自动生效）。
除特别说明外，以下结果均为：A股、**本金10万 CNY、2023-01-01 ~ 2026-10-10（约3.8年）**、
含手续费、T+1、100股整手、±10%/20%涨跌停规则。**CAGR = 年化收益率**。

### 稳定组合（单账户双引擎，推荐基线）

| 策略 | 标的池 | 总收益 | 年化 | 最大回撤 | PF | 分年 |
|---|---|---|---|---|---|---|
| **ComboSteady** | 四大行 + 27只动量池 | +109.2% | +21.6% | 8.4% | 3.82 | +12.9 / +31.3 / +10.1 / +28.2 |
| TopRot | 27只横截面动量轮动 | +172.0% | +30.4% | 15.5% | 3.83 | +2.1 / +28.4 / +30.3 / +59.3 |

ComboSteady = 银行慢腿（MacdPreGateW，持有整段）+ 月度动量轮动腿（TopRot），
同一账户共享现金：年年正收益、45个月32胜、最差月 −2.8%。
TopRot 每≤30天换持池内10日动量前2，−10%认错清仓，年线（MA250）向上才可入选。

### 四大行（601398 / 601288 / 601988 / 601939）

| 策略 | 总收益 | 年化 | 最大回撤 | PF | 笔数 |
|---|---|---|---|---|---|
| MacdPreGateW | +104.5% | +20.9% | 13.9% | 9.90 | 11 |
| RSIPlainW | +84.7% | +17.7% | 7.4% | 48.0 | 18 |

### 银行7只（四大行 + 600036 / 600016 / 000001）

| 策略 | 总收益 | 年化 | 最大回撤 | PF | 笔数 | 胜率 |
|---|---|---|---|---|---|---|
| TrendGridTradingStrategySpot | +89.5% | +18.5% | 15.9% | 8.25 | 21 | 67% |
| GridBank10 | +84.7% | +17.7% | 11.3% | 8.34 | 57 | 93% |
| RSIPlainBanks | +57.9% | +12.9% | 6.7% | 7.94 | 32 | 81% |
| MacdDip5 | +54.0% | +12.1% | 12.5% | 1.98 | 212 | 44% |
| VolPriceSpot | +46.1% | +10.6% | 9.7% | 4.96 | 64 | 58% |
| TrendFollowSpot | +41.5% | +9.7% | 15.1% | 1.79 | 352 | 45% |
| DcaFixed | +38.1% | +8.9% | 9.0% | 2.36 | 94 | 61% |
| BaseSpotBanks | +28.1% | +6.8% | 12.4% | 5.46 | 24 | 54% |
| BankMACross（基线） | +13.0% | +3.3% | 3.6% | 1.84 | 113 | 64% |

### 龙头18只（300750 / 002594 / 688981 / 600276 …）

| 策略 | 总收益 | 年化 | 最大回撤 | PF | 笔数 | 胜率 |
|---|---|---|---|---|---|---|
| VolPriceSpot | +43.8% | +10.1% | 18.8% | 1.98 | 117 | 44% |
| BaseSpot | +39.2% | +9.2% | 18.8% | 1.90 | 134 | 39% |
| RSIPlain | +38.3% | +9.0% | 9.7% | 13.3 | 13 | 85% |
| MacdDip5 | +35.2% | +8.3% | 18.4% | 1.28 | 306 | 37% |
| DcaFixed | +25.0% | +6.1% | 13.3% | 1.29 | 203 | 49% |

### 波段/防守/封存实验（同窗口，10万）

| 策略 | 思路 | 总收益 | 年化 | 最大回撤 | PF | 判决 |
|---|---|---|---|---|---|---|
| TopRotATR | MA20出场换3×ATR吊灯 | +118.7% | +23.1% | 22.6% | 2.51 | 劣于原版（回吐更大） |
| TopRotPyramid | 突破新高加仓 | +14.2% | +3.6% | 14.6% | 1.54 | 失败（追顶+底仓减半） |
| TurtleATR 20/4 | 20日突破+4×ATR吊灯 | +65.3% | +14.3% | 12.8% | 3.67 | 可用防守腿，低于基线 |
| BasketLowRisk | 低波前5篮子（34只池） | +33.6% | +8.0% | 6.5% | 1.88 | 低回撤低收益 |
| WideMultiFactor | 小市值+低换手+反转（138只） | +46.6% | +10.7% | 20.9% | 1.66 | 验证因子；封存（不做小市值） |
| IndustryRot | 行业动量前3（大票口径） | +46.1% | +10.6% | 13.1% | 1.66 | 有效但弱于个股轮动 |
| PeadDrift | 财报后漂移（同比≥20%，持60天） | +23.7% | +5.8% | 7.2% | 1.92 | 薄但正期望 |
| Supermarket（死扛原版） | 超市战法：一手一只+15%卖 | +61.8% | +13.6% | 18.6% | 2.22 | 86%胜率是幻觉 |
| SupermarketStop −6% | 加6%止损 | +93.7% | +19.2% | 18.5% | 1.34 | 超市系最优，仍逊于组合 |

对照基准（同窗口）：7只银行买入持有≈+99%，18只龙头≈+58%。
说明：动量/轮动收益集中在2024–2026 AI主题牛市；带年线/周线门禁的策略依赖
引擎的区间预热能力。历史收益不代表未来。

### 因子研究（2026-10）

Baostock日线现携带流动性/估值因子列，策略可直接引用。横截面Rank IC
（对20日前瞻收益，2023-01~2026-10）：

- **宽池（138只随机样本）**：小市值溢价确认（小 +1.86% vs 大 +0.77%/20天）、
  非流动性 IC +0.067、低换手/低波为正——但**全市场动量是反转的**（mom60 IR −0.41）。
- **精选池**：mom10 轻微为正（IC +0.02）——TopRot 的超额来自精选池（主题beta），
  这也是它最大的风险来源。
- 因子倾斜进 TopRot（低波/低换手硬过滤或加分制）全部劣化（+172% → −3%~+30%）。
- **股票池章程：不做小市值**（流动性/退市风险/幸存偏差），现有池最小流通市值约480亿。

## 安装

### 本地安装

```bash
git clone https://github.com/lzy1102/bullseye.git
cd bullseye
pip install -r requirements.txt          # 或 pip install -e .
```

### Docker 安装

```bash
docker build -t bullseye:latest .
# 或
make build && make quickstart
```

A股数据源：`pip install tushare akshare baostock exchange-calendars`
（**baostock 免token**，本项目数据默认走 baostock qfq）。

## 快速开始

### 1. 写策略（Freqtrade 接口直接可用）

```python
from bullseye.strategy import IStrategy
from pandas import DataFrame

class MyStrategy(IStrategy):
    timeframe = '1d'

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['ma20'] = dataframe['close'].rolling(20).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['close'] > dataframe['ma20']) & (dataframe['volume'] > 0),
            ['enter_long', 'enter_tag']
        ] = (1, 'above_ma20')
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['close'] < dataframe['ma20']) & (dataframe['volume'] > 0),
            ['exit_long', 'exit_tag']
        ] = (1, 'below_ma20')
        return dataframe
```

> `@informative` 多周期方法在回测与实盘中都会执行并做防未来函数合并；
> 回测需先下载对应周期数据（`download-data --timeframes 1h,1d`），
> 缺失时警告并跳过该腿，请用 `if "col_1d" in dataframe.columns` 防御。

### 2. 配置（A股示例，见 `config.yaml.example`）

```yaml
market_type: stock
settlement: t1            # A股T+1
stake_currency: CNY
dry_run: true
dry_run_wallet: 100000
stock:
  datafeed: baostock      # akshare | tushare | baostock
  adjust: qfq
pairlist:
  - method: StaticPairList
    config:
      pairs: [601398.SH, 601288.SH, 601988.SH, 601939.SH]
strategy: ComboSteady
strategy_path: user_data/strategies
timeframe: 1d
datadir: user_data/data
dataformat_ohlcv: parquet
backtest:
  fee: 0.001
  fill_next_open: false
```

### 3. 下载数据

```bash
bullseye download-data --market stock --datafeed baostock \
    --pairs 601398.SH,601288.SH --timeframes 1d \
    --timerange 20150101-20261010 --adjust qfq --data-format parquet
```

### 4. 回测

```bash
bullseye backtesting --strategy MacdPreGateW --config config.yaml \
    --timerange 20230101-20261010 --initial-balance 100000 \
    --stake-amount 25000 --max-open-trades 4
```

> 各策略的配套配置（标的池不同）可按第2节示例自建，例如：
> 四大行池用 `--pairs 601398.SH,601288.SH,601988.SH,601939.SH`，
> 轮动组合池见 `docs/strategies.md` 第11/12节。

### 5. 超参优化

```bash
bullseye hyperopt --strategy MyStrategy --epochs 200 --loss sharpe \
    --timerange 20230101-20241231 --min-trades 20
```

### 6. 实盘 / 模拟盘

```bash
bullseye trade --strategy ComboSteady --config config.yaml --dry    # 模拟盘
bullseye trade --strategy ComboSteady --config config.yaml --live   # 实盘（需网关）
```

## 实盘网关与自定义券商通道

系统内建 miniQMT（A股）、CCXT（加密）、CTP（期货）网关。**没有 miniQMT 通道时**，
用 `market_type: custom` + HTTP 订单桥：本地起一个桥接服务（可用 easytrader 等
驱动券商客户端），按标准契约暴露 REST 接口，框架自动通过它下单/对账：

```yaml
market_type: custom
custom:
  gateway: "bullseye.gateway.template.gateway_template.TemplateGateway"
  base_url: "http://127.0.0.1:8000"
  token: "***"
  kill_switch_file: "user_data/KILL_TRADING"   # 建文件即熔断，只拦新单
  datafeed: baostock
execution:
  order_timeout: 10
  order_poll_interval: 0.5
```

桥接服务契约（请求/返回字段、状态枚举、对账与熔断要求）与验收清单见
[`docs/gateway-development.md`](docs/gateway-development.md)，
参考实现 `bullseye/gateway/template/gateway_template.py`。

## 测试

```bash
pytest tests/ -v            # 全量
pytest tests/test_backtesting/ -v
```

当前状态：**409 passed, 9 skipped**（跳过项需 akshare/tushare/baostock 网络或 token）。

## 与 Freqtrade 兼容性

| 特性 | Bullseye | Freqtrade |
|------|----------|-----------|
| IStrategy 接口 | ✅ v3 | v3 |
| @informative 多周期 | ✅（防未来函数合并，回测+实盘） | ✅ |
| 可超参化参数 | ✅ | ✅ |
| DataProvider | ✅ | ✅ |
| 各种回调 | ✅ | ✅ |
| 回测 | ✅ | ✅ |
| 超参优化 | ✅ | ✅ |
| 加密交易 | ✅（CCXT） | ✅（CCXT） |
| A股交易 | ✅（miniQMT / 自定义桥） | ❌ |
| 期货交易 | ✅（CTP，6交易所） | ❌ |
| 事件驱动 | ✅ | ❌ |
| 结构化异常 | ✅ | ❌ |

## 文档索引

- [策略总览与收益](docs/strategies.md) —— 每个策略的逻辑、参数、回测与实验记录
- [网关开发标准](docs/gateway-development.md) —— 自定义实盘通道对接
- [趋势判断基准](docs/trend-detection-benchmark.md) —— 9种趋势方法对比实验

## 许可证

MIT License，详见 LICENSE 文件。

## 致谢

- [Freqtrade](https://github.com/freqtrade/freqtrade) —— 策略接口设计
- [VeighNa (vnpy)](https://github.com/vnpy/vnpy) —— 网关与事件引擎架构
- [CCXT](https://github.com/ccxt/ccxt) —— 统一加密交易所API
