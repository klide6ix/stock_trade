#!/bin/bash

PID_FILE=".trader.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "실행 중인 트레이더가 없습니다."
    exit 1
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    rm "$PID_FILE"
    echo "트레이더 종료 완료 (PID: $PID)"
else
    echo "프로세스를 찾을 수 없습니다. PID 파일을 삭제합니다."
    rm "$PID_FILE"
fi
