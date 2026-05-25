#!/bin/bash

# 設定碰到錯誤就提早結束腳本 (Fail-fast)
set -e

echo "=================================================="
echo "        TaiwanAlpha 🇹🇼📈 一鍵啟動腳本"
echo "=================================================="

echo -e "\n[1/5] 檢查專案目錄結構..."
if [ ! -d "data" ]; then
    mkdir data
    echo "  - 已自動建立 data/ 資料夾。"
else
    echo "  - data/ 資料夾已存在。"
fi

echo -e "\n[2/5] 安裝/檢查依賴套件..."
# 伺服器環境若預設為 python3，這裡可以視情況改成 pip3
pip install -r requirements.txt

echo -e "\n[3/5] 初始化 DuckDB 資料庫架構 (Silver/Gold Layer)..."
python3 storage/schema.py

echo -e "\n[4/5] 啟動爬蟲抓取 TWSE 最新籌碼資料 (Ingestion)..."
python3 ingestion/twse_ingestion.py

echo -e "\n[5/5] 執行特徵工程計算 Alpha 訊號 (Processing)..."
python3 processing/feature_engineering.py

echo -e "\n=================================================="
echo " 🚀 所有資料處理完畢！準備啟動 FastAPI 伺服器..."
echo " 👉 測試介面 (Swagger UI): http://<伺服器IP>:8000/docs"
echo " (如需關閉伺服器，請按 Ctrl + C)"
echo "=================================================="
echo ""

# 綁定 0.0.0.0 讓外部網路可以連入 API
uvicorn delivery.api:app --host 0.0.0.0 --port 8000 --reload