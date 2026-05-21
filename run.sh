#!/bin/bash
# 幕牆圖紙結構分析系統 — 啟動腳本

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "========================================="
echo "  幕牆圖紙結構分析系統"
echo "  Curtain Wall Drawing Analyzer"
echo "========================================="

# 檢查 Python
if ! command -v python3 &>/dev/null; then
    echo "錯誤: 需要 Python 3.10+"
    exit 1
fi

# 建立虛擬環境 (如不存在)
if [ ! -d "venv" ]; then
    echo ">> 建立虛擬環境..."
    python3 -m venv venv
fi

# 啟動
source venv/bin/activate

# 安裝依賴 (如需要)
if [ ! -f "venv/.deps_installed" ]; then
    echo ">> 安裝依賴..."
    pip install -r backend/requirements.txt
    touch venv/.deps_installed
fi

echo ">> 啟動服務 http://localhost:8765 ..."
cd backend
python app.py
