#!/bin/bash
# AlphaForge 開發環境啟動腳本

echo "========================================="
echo "  AlphaForge Dev Launcher"
echo "========================================="

# 1. 先檢查並清除已有的服務
echo ""
echo "[1/4] 檢查已有服務..."

BACKEND_PID=$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null)
if [ -n "$BACKEND_PID" ]; then
    echo "  ⚠️  Port 8000 已被佔用 (PID: $BACKEND_PID)，正在關閉..."
    kill $BACKEND_PID 2>/dev/null
    sleep 1
fi

FRONTEND_PID=$(lsof -nP -iTCP:3000 -sTCP:LISTEN -t 2>/dev/null)
if [ -n "$FRONTEND_PID" ]; then
    echo "  ⚠️  Port 3000 已被佔用 (PID: $FRONTEND_PID)，正在關閉..."
    kill $FRONTEND_PID 2>/dev/null
    sleep 1
fi

echo "  ✅ Port 8000 和 3000 已清空"

# 2. 啟動後端
echo ""
echo "[2/4] 啟動後端服務 (port 8000)..."
cd ~/Documents/GitHub/AlphaForge/backend
source .venv/bin/activate
nohup python main.py > /tmp/alphaforge_backend.log 2>&1 &
BACKEND_PID=$!
echo "  ✅ 後端已啟動 (PID: $BACKEND_PID)"

# 3. 啟動前端
echo ""
echo "[3/4] 啟動前端服務 (port 3000)..."
cd ~/Documents/GitHub/AlphaForge/frontend
nohup npx next dev -p 3000 > /tmp/alphaforge_frontend.log 2>&1 &
FRONTEND_PID=$!
echo "  ✅ 前端已啟動 (PID: $FRONTEND_PID)"

# 4. 等待服務啟動
echo ""
echo "[4/4] 等待服務就緒..."
sleep 5

# 檢查後端
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "  ✅ 後端 http://localhost:8000 → 運行中"
else
    echo "  ⚠️  後端可能尚未啟動，查看 /tmp/alphaforge_backend.log"
fi

# 檢查前端
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo "  ✅ 前端 http://localhost:3000 → 運行中"
else
    echo "  ⚠️  前端可能還在編譯中，若無回應請稍等或查看 /tmp/alphaforge_frontend.log"
fi

echo ""
echo "========================================="
echo "  🚀 AlphaForge 開發服務已就緒！"
echo "  📋 後端日誌: /tmp/alphaforge_backend.log"
echo "  📋 前端日誌: /tmp/alphaforge_frontend.log"
echo "========================================="
