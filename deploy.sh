#!/bin/bash
cd /root/szpu-agent || exit 1
pkill -f "uvicorn app.main" 2>/dev/null
sleep 1
rm -f server.log
# HF 镜像:bge-small-zh-v1.5 首次下载加速(国内网络)
export HF_ENDPOINT=https://hf-mirror.com
setsid nohup python3.11 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 < /dev/null &
sleep 4
echo "---HEALTH---"
curl -s -m 5 http://127.0.0.1:8000/api/health
echo
echo "---PORT---"
ss -tln | grep 8000
echo "---FW---"
firewall-cmd --add-port=8000/tcp --permanent 2>&1
firewall-cmd --reload 2>&1
echo "---LOG---"
tail -5 server.log
echo "DEPLOY_DONE"
