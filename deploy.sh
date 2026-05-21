#!/bin/bash

# ==========================================
# AlphaForge NAS 一鍵部署腳本 (v1.1)
# ==========================================
# v1.1: docker-compose backend/frontend 改用 pre-built image (commit c52843d)
#       後 --build 已成空操作; 改為先 docker build 產生 image, 再 up
#       --force-recreate 重建容器。前端必帶 NEXT_PUBLIC_API_URL build arg。

# 設定
NAS_HOST="10.0.4.3"
NAS_PORT="22"
NAS_USER="chihhaolai"
NAS_PROJECT_DIR="/volume1/homes/chihhaolai/Drive/Documents-mac-m1/GitHub/AlphaForge"

# 顯示選單
echo "=========================================="
echo "      🚀 AlphaForge 部署工具程式"
echo "=========================================="
echo "1) 更新前端 (UI/CSS/TSX 改動)"
echo "2) 更新後端 (API/Python 改動)"
echo "3) 全系統更新 (前後端同時更新)"
echo "4) 強制重新建置 (套件變動時使用 --no-cache)"
echo "q) 離開"
echo "=========================================="
read -p "請選擇部署項目 [1-4, q]: " choice

case $choice in
    1)
        DEPLOY_CMD="export PATH=/usr/local/bin:\$PATH && cd $NAS_PROJECT_DIR && sudo env DOCKER_BUILDKIT=1 docker build -t alphaforge_frontend --build-arg NEXT_PUBLIC_API_URL=/alphaforge/api ./frontend && sudo docker-compose up -d --force-recreate frontend"
        echo "正在更新前端服務..."
        ;;
    2)
        DEPLOY_CMD="export PATH=/usr/local/bin:\$PATH && cd $NAS_PROJECT_DIR && sudo env DOCKER_BUILDKIT=1 docker build -t alphaforge_backend ./backend && sudo docker-compose up -d --force-recreate backend"
        echo "正在更新後端服務..."
        ;;
    3)
        DEPLOY_CMD="export PATH=/usr/local/bin:\$PATH && cd $NAS_PROJECT_DIR && sudo env DOCKER_BUILDKIT=1 docker build -t alphaforge_backend ./backend && sudo env DOCKER_BUILDKIT=1 docker build -t alphaforge_frontend --build-arg NEXT_PUBLIC_API_URL=/alphaforge/api ./frontend && sudo docker-compose up -d --force-recreate"
        echo "正在更新全系統服務..."
        ;;
    4)
        DEPLOY_CMD="export PATH=/usr/local/bin:\$PATH && cd $NAS_PROJECT_DIR && sudo env DOCKER_BUILDKIT=1 docker build --no-cache -t alphaforge_backend ./backend && sudo env DOCKER_BUILDKIT=1 docker build --no-cache -t alphaforge_frontend --build-arg NEXT_PUBLIC_API_URL=/alphaforge/api ./frontend && sudo docker-compose up -d --force-recreate"
        echo "正在強制重新建置所有服務..."
        ;;
    q)
        echo "離開中..."
        exit 0
        ;;
    *)
        echo "無效的選擇"
        exit 1
        ;;
esac

# 執行 SSH 部署
echo "正在連線至 NAS ($NAS_HOST:$NAS_PORT)..."
ssh -t -p "$NAS_PORT" "$NAS_USER@$NAS_HOST" "$DEPLOY_CMD"

if [ $? -eq 0 ]; then
    echo "=========================================="
    echo "✅ 部署任務已完成！"
    echo "🌍 存取網址: https://$NAS_HOST/alphaforge"
    echo "=========================================="
else
    echo "❌ 部署失敗，請檢查網路連線或 NAS 狀態。"
fi
