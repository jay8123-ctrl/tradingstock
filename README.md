# TradingStock — 一人 AI 交易台

美股（Alpaca 模拟盘）+ 马股（Moomoo MY 研究）纯多头、无杠杆（1x 现金）交易系统。

## 快速启动步骤（Windows / Mac / Linux VPS 通用）

### 第 1 步：安装基础工具
1. 安装 **Python 3.11+**（Windows 安装时务必勾选 `Add python.exe to PATH`）：https://www.python.org/downloads/
2. 安装 **Git**：https://git-scm.com/downloads

### 第 2 步：下载本项目到你的电脑或 VPS
打开终端（Windows 打开 **PowerShell**，Mac/Linux 打开 **Terminal**），依次运行：

```bash
git clone https://github.com/jay8123-ctrl/tradingstock.git
cd tradingstock
```

### 第 3 步：创建虚拟环境并安装依赖
**Windows (PowerShell)：**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Mac / Linux / VPS：**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 第 4 步：填入你的 Alpaca Paper API Key（绝不上传 Git）
1. 复制模板文件：
   - **Windows (PowerShell)**：`copy .env.example .env`
   - **Mac / Linux / VPS**：`cp .env.example .env && chmod 600 .env`
2. 用记事本（Windows: `notepad .env`）或 `nano .env` 打开 `.env`，填入你的 **Alpaca Paper Trading** 密钥：
   ```env
   TRADING_MODE=PAPER
   ALPACA_PAPER_API_KEY=你的_Paper_Key
   ALPACA_PAPER_API_SECRET=你的_Paper_Secret
   ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets
   ```

### 第 5 步：跑通自测、拉数据、启动模拟盘
```bash
# 1. 跑 7 项风控与故障自测（应显示 ALL 7 DAY-5 FAULT TESTS PASSED!）
python bot/test_day5_faults.py

# 2. 更新最新美股/马股研究数据
python bot/data_pipeline.py

# 3. 拉取 Alpaca 4 年官方美股分钟线（需要已填好 .env）
python bot/alpaca_intraday_downloader.py

# 4. 运行 SW-04 模拟盘机器人（MODE: PAPER，自动挂交易所端止损）
python bot/paper_bot.py
```

## 安全硬规则
- 永远保持 `TRADING_MODE=PAPER`，实盘必须完成 **30 笔以上且对得上回测的模拟盘交易** 并由你书面确认「可以上实盘」。
- `.env` 已在 `.gitignore` 中，切勿将密钥发到聊天框或提交到 GitHub。
