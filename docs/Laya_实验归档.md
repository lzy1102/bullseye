# Laya 决策编码器 实验归档（信号风险评分：防深追/防亏损）

> 日期：2026-09-22/23 ｜ 环境：70 测试服（192.168.3.70），docker 容器 `laya`（freqtrade 镜像 + torch 2.14 CPU + transformers 5.17 + laya 0.3.5）
> 结论先行：**否决，未融入策略**。K线文本零样本无区分度；冻结编码器 embedding 在"深追"目标上样本外 AUC **0.459**（还不如原始特征的 **0.577**）；改用真实成交标签（536 笔）样本太小、全为噪声。**K线-only 的信息天花板 ~0.58 AUC，第三次验证一致。**

## 0. 背景与目标

- 用户提案：本地部署 [Laya](https://github.com/NandhaKishorM/laya)（非自回归决策编码器，ModernBERT 编码器 + 类型化决策头 choice/score/noul，单次前向 33ms/T4），对买卖信号打分 → 防止深追与亏损
- 官方 honest limits（决定了路线）：base checkpoint 在决策任务上零样本接近随机（0.36 vs 0.318 随机基线），**价值全在自己的领域数据微调**；输入是文本/JSON（看不了图片），"只给K线"必须序列化成文本
- 本项目既有证据：25+ 维入场特征对深追的 AUC ≤0.58；逆势不是问题；唯一弱组是"贴 7 日极值逆势"（已做成 V5 闸门）

## 1. 部署（70 测试服，全离线）

- 直连 PyPI/HF 在 70 上基本不可用（torch 554MB 下载速度 ≈0）→ 方案：**本机下载 → 局域网 SFTP → 容器离线安装**
  - wheel：36 个（cp314 manylinux，含 laya 0.3.5、transformers 5.17、sentence 等）；**torch 用 CPU 版**（CUDA 版依赖 `cuda-toolkit==13.0.3` 无法离线满足）
  - 模型：`convaiinnovations/laya` 英文 checkpoint 根目录（843MB `model.safetensors` + encoder config + tokenizer），从 HF 直接下载
  - 容器：`docker run -d --name laya ... freqtradeorg/freqtrade:stable`（本地已有镜像，避开 Docker Hub 不可达）；`pip install --no-index --find-links` 逐包 `--no-deps` 安装
- 冒烟：`laya.load('/workspace/model', device='cpu')` 17.5s，单次 3 问 ~1.2s（CPU，30m 频率够用）

## 2. 数据集（喂"我们的买入信号"）

- **信号集**：V4 入场逻辑扫描 5 主币 30m（2025-01→2026-09），抓全部信号（含因 max_open=1 未成交的），**3692 条**（多 1608 / 空 2084）
- **输入（只给K线）**：最近 24 根 30m 的 收/高/低/量比 + 日线 trend/dev60/RSI/ATR/网格深度，序列化为文本
- **代理标签**：deep(72h逆行≥8%) 773 (20.9%)｜trend_rev(72h内日线翻向) 476 (12.9%)｜loss72 1682 (45.6%)｜bad72 1158 (31.4%)
- **真实标签**：主池回测成交 536 笔与信号对齐（12 笔未匹配）：深追(补仓≥3) 69｜亏损 23｜趋势反转强平 21

## 3. 结果

### 3.1 零样本冒烟（3 例：真实深追单 / 真实浅单 / 当前持仓）
`deep_chase` 概率 0.150 / 0.161 / 0.166，`danger` 1.01 / 0.93 / 0.96 —— **无区分度**（官方限制复现）

### 3.2 冻结编码器 embedding 探针（3692 信号，时间切分：train ≤2026-03 = 3090 / test ≥2026-04 = 602）

| 目标 | Laya emb AUC | 原始特征 AUC |
|---|---|---|
| deep（深追） | **0.459** | **0.577** |
| trend_rev（强平代理） | 0.585 | 0.594 |
| loss72（亏损代理） | 0.539 | 0.466 |

### 3.3 真实成交探针（536 笔，train 430 / test 106，正例 7-11 个）

| 目标 | A:真实标签训练 emb/raw | B:代理标签训练 emb/raw |
|---|---|---|
| deep_real | 0.412 / 0.484 | 0.500 / 0.464 |
| loss_real | 0.309 / 0.486 | 0.448 / 0.463 |
| trev_real | 0.332 / 0.537 | 0.411 / 0.677 |

→ 测试正例仅 7-11 个、AUC 波动 ±0.1，全是噪声；**536 笔真实成交不足以训练任何模型**

## 4. 结论与边界

1. **K线-only 无增量**：Laya embedding 在最重要的深追目标上不如原始数值特征；与 25 维特征分析、FreqAI 波动仓位实验的结论一致（信息天花板 ~0.58 AUC）
2. 换更强模型/更长上下文不解决"信息问题"；真实标签扩量（30-50 币 → 5000+ 笔）只解决"样本量"，不解决"有没有信息"
3. **若重启该线的正确姿势**：给模型加外部信息（资金费/持仓量/爆仓/新闻文本），这才是文本编码器相对数值模型的主场；或直接租卡微调（70 的 GTX1650 4GB 只能冻结编码器）
4. 未上线、未融入策略；V5（极值逆势闸门）仍为本项目唯一验证通过的风控改进

## 5. 资产位置

- 脚本：`utils/laya/`（build_dataset / extract_embeddings / probe_signals / match_real_trades / probe_real_trades / deploy_to_70）
- 70 测试服：容器 `laya`；`/root/laya/{model(843M), wh, wh_cpu, laya_dataset.jsonl, laya_real_labels.jsonl, laya_emb.npz, *.log}`（清理：`docker rm -f laya && rm -rf /root/laya`）
