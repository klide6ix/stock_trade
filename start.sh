#!/bin/bash

PID_FILE=".trader.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "이미 실행 중입니다. (PID: $PID)"
        exit 1
    fi
fi

# 기존에 8501 포트 점유 중인 프로세스 정리
EXISTING=$(lsof -ti :8501 2>/dev/null)
if [ -n "$EXISTING" ]; then
    echo "기존 포트 8501 프로세스 종료 (PID: $EXISTING)"
    kill "$EXISTING" 2>/dev/null
fi

mkdir -p logs
echo "트레이더 시작..."
nohup python main.py > logs/startup.log 2>&1 &
echo $! > "$PID_FILE"
echo "실행 완료 (PID: $(cat $PID_FILE))"
echo "대시보드: http://localhost:8501"
