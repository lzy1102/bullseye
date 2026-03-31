# Bullseye 项目补全计划

## 项目概述

将 Bullseye 打造为与 Freqtrade 完全兼容的量化交易框架，补充缺失的 CLI 命令、分析工具、RPC 系统和数据管理功能。

---

## 第一阶段：核心 CLI 命令补全

### 1.1 配置管理命令

#### `bullseye create-userdir`
**功能**：创建用户数据目录结构
**参考**：Freqtrade `create-userdir` 命令
**输出目录结构**：
```
user_data/
├── backtest_results/
├── data/
├── hyperopts/
├── logs/
├── notebooks/
├── plot/
├── strategies/
└── config.json
```

#### `bullseye new-config`
**功能**：交互式生成配置文件
**交互内容**：
- 市场类型选择 (crypto/stock/future)
- 交易所选择
- 数据库配置
- Telegram/API 配置

#### `bullseye show-config`
**功能**：显示解析后的完整配置
**输出**：YAML 格式的完整配置（包含默认值）

### 1.2 列表命令补全

#### `bullseye list-markets`
**功能**：列出交易所支持的市场
**参数**：
- `--exchange`：指定交易所
- `--quote`：按计价货币筛选
- `--active-only`：只显示活跃市场

#### `bullseye list-pairs`
**功能**：列出可交易的交易对
**参数**：
- `--quote`：按计价货币筛选
- `--print-json`：JSON 格式输出

#### `bullseye list-hyperoptloss`
**功能**：列出可用的超参数损失函数
**内置损失函数**：
- `ShortTradeDurHyperOptLoss`
- `OnlyProfitHyperOptLoss`
- `SharpeHyperOptLoss`
- `SharpeHyperOptLossDaily`
- `SortinoHyperOptLoss`
- `SortinoHyperOptLossDaily`
- `CalmarHyperOptLoss`

#### `bullseye list-data`
**功能**：列出已下载的历史数据
**参数**：
- `--exchange`：指定交易所
- `--data-format`：数据格式

### 1.3 回测相关命令

#### `bullseye backtesting-show`
**功能**：显示历史回测结果
**参数**：
- `--export-filename`：指定结果文件
- `--show-all`：显示所有结果

#### `bullseye show-trades`
**功能**：显示交易记录
**参数**：
- `--db-url`：数据库路径
- `--trade-ids`：指定交易ID
- `--print-json`：JSON 格式输出

### 1.4 其他命令

#### `bullseye test-pairlist`
**功能**：测试交易对列表配置
**输出**：实际会交易的交易对列表

#### `bullseye convert-db`
**功能**：数据库格式转换
**支持转换**：SQLite ↔ PostgreSQL ↔ MySQL

---

## 第二阶段：分析工具实现

### 2.1 前瞻偏差分析 (`lookahead-analysis`)

**目的**：检测策略是否无意中使用了未来数据

**实现原理**：
1. 使用完整数据运行策略生成信号
2. 使用截断数据（去掉最后N根K线）运行策略
3. 对比两组信号的差异
4. 如果信号不同，说明存在前瞻偏差

**文件位置**：`bullseye/optimize/analysis/lookahead.py`

**CLI 命令**：
```bash
bullseye lookahead-analysis --strategy MyStrategy --timerange 20240101-20241231
```

**输出内容**：
- 检测到的偏差指标列表
- 偏差严重程度评分
- 建议修复方案

### 2.2 递归偏差分析 (`recursive-analysis`)

**目的**：检测递归公式（如EMA）导致的计算偏差

**实现原理**：
1. 使用不同的 `startup_candle_count` 运行多次回测
2. 对比不同启动周期下的信号差异
3. 识别对启动周期敏感的指标

**文件位置**：`bullseye/optimize/analysis/recursive.py`

**CLI 命令**：
```bash
bullseye recursive-analysis --strategy MyStrategy --timerange 20240101-20241231
```

**输出内容**：
- 递归敏感指标列表
- 推荐的 startup_candle_count
- 指标稳定性评分

### 2.3 回测结果分析 (`backtesting-analysis`)

**目的**：深入分析回测结果的入场/出场信号

**分析维度**：
- 按入场标签分组统计
- 按出场标签分组统计
- 按交易对分组统计
- 被拒绝的信号分析

**文件位置**：`bullseye/data/entryexitanalysis.py`

**CLI 命令**：
```bash
bullseye backtesting-analysis --export-filename backtest_results.json --analysis-groups entry_tag exit_tag pair
```

**输出格式**：
```json
{
  "entry_tag_analysis": {
    "rsi_oversold": {
      "total_trades": 100,
      "win_rate": 0.65,
      "avg_profit": 0.025,
      "total_profit": 2.5
    }
  }
}
```

---

## 第三阶段：RPC 系统实现

### 3.1 Telegram 集成

**文件位置**：`bullseye/rpc/telegram.py`

**功能清单**：
- [ ] 机器人启动/停止通知
- [ ] 交易入场/出场通知
- [ ] 定时状态报告
- [ ] 交互式命令：
  - `/start` - 启动机器人
  - `/stop` - 停止机器人
  - `/status` - 查看当前状态
  - `/profit` - 查看收益统计
  - `/balance` - 查看账户余额
  - `/trades` - 查看当前持仓
  - `/history` - 查看交易历史
  - `/forcesell` - 强制卖出
  - `/forcebuy` - 强制买入

**配置示例**：
```yaml
telegram:
  enabled: true
  token: "your_bot_token"
  chat_id: "your_chat_id"
  notification_settings:
    status: on
    warning: on
    startup: on
    entry: on
    exit: on
```

### 3.2 REST API Server

**文件位置**：`bullseye/rpc/api_server/`

**API 端点规划**：

#### 交易管理
- `POST /api/v1/trade` - 创建交易
- `POST /api/v1/trade/{trade_id}/sell` - 卖出
- `DELETE /api/v1/trade/{trade_id}` - 取消交易
- `GET /api/v1/trades` - 获取交易列表
- `GET /api/v1/trade/{trade_id}` - 获取交易详情

#### 状态查询
- `GET /api/v1/status` - 机器人状态
- `GET /api/v1/balance` - 账户余额
- `GET /api/v1/profit` - 收益统计
- `GET /api/v1/performance` - 性能指标

#### 配置管理
- `GET /api/v1/config` - 获取配置
- `POST /api/v1/config` - 更新配置
- `GET /api/v1/pairlist` - 获取交易对列表

#### 回测控制
- `POST /api/v1/backtest` - 启动回测
- `GET /api/v1/backtest/{backtest_id}` - 获取回测结果
- `DELETE /api/v1/backtest/{backtest_id}` - 停止回测

#### 数据管理
- `GET /api/v1/logs` - 获取日志
- `GET /api/v1/chart/{pair}` - 获取图表数据

**认证方式**：JWT Token

### 3.3 Webhook 支持

**文件位置**：`bullseye/rpc/webhook.py`

**功能**：
- 支持自定义 Webhook URL
- 支持多种格式：form, json, raw
- 支持重试机制（指数退避）
- 可配置不同消息类型的处理方式

**配置示例**：
```yaml
webhook:
  enabled: true
  url: "https://your-webhook-url.com"
  format: json
  retry_count: 3
  timeout: 10
```

---

## 第四阶段：数据管理完善

### 4.1 历史数据下载

**文件位置**：`bullseye/commands/data_commands.py`

**功能完善**：

#### `bullseye download-data`
**参数**：
- `--exchange`：交易所名称
- `--pairs`：交易对列表
- `--timeframes`：时间框架列表
- `--timerange`：时间范围
- `--dl-trades`：下载交易数据（而非OHLCV）
- `--data-format`：数据格式（feather/json/parquet）
- `--prepend`：在现有数据前添加

**实现细节**：
- 支持多线程并行下载
- 支持增量更新
- 支持数据验证
- 支持自动重试

### 4.2 数据格式支持

**文件位置**：`bullseye/data/history/`

**新增文件**：
- `featherdatahandler.py` - Feather 格式处理
- `jsondatahandler.py` - JSON 格式处理
- `parquetdatahandler.py` - Parquet 格式处理

**统一接口**：
```python
class IDataHandler(ABC):
    @abstractmethod
    def ohlcv_get(self, pair: str, timeframe: str) -> DataFrame: ...
    
    @abstractmethod
    def ohlcv_store(self, pair: str, timeframe: str, data: DataFrame) -> None: ...
    
    @abstractmethod
    def trades_get(self, pair: str) -> DataFrame: ...
    
    @abstractmethod
    def trades_store(self, pair: str, data: DataFrame) -> None: ...
```

### 4.3 数据转换命令

#### `bullseye convert-data`
**功能**：转换 OHLCV 数据格式
**参数**：
- `--input-format`：输入格式
- `--output-format`：输出格式
- `--exchange`：交易所

#### `bullseye convert-trade-data`
**功能**：转换交易数据格式

#### `bullseye trades-to-ohlcv`
**功能**：将交易数据聚合为 OHLCV
**参数**：
- `--timeframe`：目标时间框架
- `--exchange`：交易所

---

## 第五阶段：策略接口补全

### 5.1 新增回调方法

**文件位置**：`bullseye/strategy/interface.py`

#### 自定义 ROI
```python
def custom_roi(self, pair: str, current_time: datetime, current_rate: float,
               current_profit: float, **kwargs) -> Optional[float]:
    """自定义 ROI 逻辑，返回目标收益率或 None"""
    pass
```

#### 自定义出场价格
```python
def custom_exit_price(self, pair: str, trade: Trade, current_time: datetime,
                      proposed_rate: float, current_profit: float,
                      exit_tag: Optional[str], **kwargs) -> float:
    """自定义出场价格"""
    return proposed_rate
```

#### 订单价格调整
```python
def adjust_entry_price(self, pair: str, current_time: datetime,
                       proposed_rate: float, entry_tag: Optional[str],
                       side: str, **kwargs) -> float:
    """调整入场订单价格"""
    return proposed_rate

def adjust_exit_price(self, pair: str, trade: Trade, current_time: datetime,
                      proposed_rate: float, current_profit: float,
                      exit_tag: Optional[str], **kwargs) -> float:
    """调整出场订单价格"""
    return proposed_rate
```

#### 订单成交回调
```python
def order_filled(self, pair: str, trade: Trade, order: Order,
                 current_time: datetime, **kwargs) -> None:
    """订单完全成交后调用"""
    pass
```

### 5.2 交易对锁定机制

```python
def lock_pair(self, pair: str, until: datetime, reason: str) -> None:
    """锁定交易对，在指定时间前不打开新仓位"""
    pass

def unlock_pair(self, pair: str) -> None:
    """解锁交易对"""
    pass

def is_pair_locked(self, pair: str, current_time: datetime) -> bool:
    """检查交易对是否被锁定"""
    pass
```

### 5.3 内部功能完善

- [ ] 完整的 `should_exit()` 逻辑
- [ ] `ft_stoploss_reached()` 完整实现
- [ ] `min_roi_reached()` 完整实现
- [ ] 交易对锁定机制集成到交易循环

---

## 第六阶段：高级功能实现

### 6.1 绘图工具

#### `bullseye plot-dataframe`
**功能**：绘制 K 线和指标图表
**参数**：
- `--pair`：交易对
- `--timerange`：时间范围
- `--indicators`：要显示的指标
- `--plot-limit`：绘制的K线数量
- `--trade-source`：显示交易记录

**输出**：HTML 文件（使用 Plotly）

#### `bullseye plot-profit`
**功能**：绘制收益曲线
**参数**：
- `--export-filename`：回测结果文件
- `--timerange`：时间范围

**输出**：HTML 文件

### 6.2 超参数优化完善

#### `bullseye hyperopt-list`
**功能**：列出历史优化结果
**参数**：
- `--best`：只显示最佳结果
- `--profitable`：只显示盈利结果
- `--export-csv`：导出为 CSV

#### `bullseye hyperopt-show`
**功能**：显示优化结果详情
**参数**：
- `--hyperopt-id`：优化结果ID
- `--best`：显示最佳结果
- `--print-json`：JSON 格式输出

### 6.3 策略升级工具

#### `bullseye strategy-updater`
**功能**：自动升级旧版本策略
**支持升级**：
- Freqtrade v2 → v3 策略格式
- 旧版 Bullseye → 新版格式

---

## 实施建议

### 开发顺序

1. **第一阶段**（1-2周）：CLI 命令补全
   - 先实现配置管理命令
   - 再实现列表命令

2. **第二阶段**（2-3周）：分析工具
   - 前瞻偏差分析（最重要）
   - 递归偏差分析
   - 回测结果分析

3. **第三阶段**（2-3周）：RPC 系统
   - Telegram 集成
   - REST API Server（基础端点）

4. **第四阶段**（1-2周）：数据管理
   - 完善数据下载
   - 实现数据转换

5. **第五阶段**（1-2周）：策略接口
   - 补充回调方法
   - 实现锁定机制

6. **第六阶段**（2-3周）：高级功能
   - 绘图工具
   - 优化结果管理

### 依赖安装

```bash
# 基础依赖已存在

# 绘图
pip install plotly kaleido

# API Server
pip install fastapi uvicorn websockets python-jose

# Telegram
pip install python-telegram-bot

# 数据格式
pip install pyarrow  # for parquet
```

### 测试策略

每个功能实现后应：
1. 编写单元测试
2. 进行集成测试
3. 与 Freqtrade 行为对比验证
4. 更新文档

---

## 附录：Freqtrade 命令完整列表

```
trade                    - 启动交易机器人
create-userdir           - 创建用户数据目录
new-config               - 创建新配置
show-config              - 显示解析后的配置
new-strategy             - 创建新策略
download-data            - 下载历史数据
convert-data             - 转换 OHLCV 数据格式
convert-trade-data       - 转换交易数据格式
trades-to-ohlcv          - 交易数据转 OHLCV
list-data                - 列出已下载数据
backtesting              - 运行回测
backtesting-show         - 显示历史回测结果
backtesting-analysis     - 回测结果分析
edge                     - Edge 模块（已弃用）
hyperopt                 - 超参数优化
hyperopt-list            - 列出优化结果
hyperopt-show            - 显示优化结果详情
list-exchanges           - 列出支持的交易所
list-markets             - 列出市场
list-pairs               - 列出交易对
list-strategies          - 列出策略
list-hyperoptloss        - 列出损失函数
list-freqaimodels        - 列出 FreqAI 模型
list-timeframes          - 列出时间框架
show-trades              - 显示交易记录
test-pairlist            - 测试交易对列表配置
convert-db               - 转换数据库
install-ui               - 安装 FreqUI
plot-dataframe           - 绘制 K 线和指标
plot-profit              - 绘制收益曲线
webserver                - 启动 Web 服务器
strategy-updater         - 策略升级工具
lookahead-analysis       - 前瞻偏差分析
recursive-analysis       - 递归偏差分析
```
