@echo off
cd /d "%~dp0.."
echo ================================================== >> bot\daily_run.log
echo [%date% %time%] Starting TradingStock SW-04 Daily Run >> bot\daily_run.log
.\.venv\Scripts\python.exe bot\data_pipeline.py >> bot\daily_run.log 2>&1
.\.venv\Scripts\python.exe bot\paper_bot.py >> bot\daily_run.log 2>&1
echo [%date% %time%] Finished Daily Run >> bot\daily_run.log
