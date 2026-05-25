@echo off
:: 設定終端機顯示 UTF-8 中文避免亂碼
chcp 65001 >nul

echo ==================================================
echo         TaiwanAlpha 🇹🇼📈 一鍵啟動腳本
echo ==================================================

echo.
echo [1/5] 檢查專案目錄結構...
if not exist data (
    mkdir data
    echo  - 已自動建立 data/ 資料夾。
) else (
    echo  - data/ 資料夾已存在。
)

echo.
echo [2/5] 安裝/檢查依賴套件...
pip install -r requirements.txt

echo.
echo [3/5] 初始化 DuckDB 資料庫架構 (Silver/Gold Layer)...
python storage/schema.py

echo.
echo [4/5] 啟動爬蟲抓取 TWSE 最新籌碼資料 (Ingestion)...
python ingestion/twse_ingestion.py

echo.
echo [5/5] 執行特徵工程計算 Alpha 訊號 (Processing)...
python processing/feature_engineering.py

echo.
echo ==================================================
echo  🚀 所有資料處理完畢！準備啟動 FastAPI 伺服器...
echo  👉 API 測試介面 (Swagger UI): http://localhost:8000/docs
echo  (如需關閉伺服器，請在此視窗按下 Ctrl + C)
echo ==================================================
echo.

uvicorn delivery.api:app --reload --port 8000