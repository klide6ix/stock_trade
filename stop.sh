#!/bin/bash

PID_FILE=".trader.pid"
TERMINATED=0

# 1) main.py 프로세스 종료 (.trader.pid 기준)
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "트레이더 종료 (PID: $PID)"
        TERMINATED=1
    fi
    rm -f "$PID_FILE"
fi

# 2) main.py 의 자식이었던 streamlit 프로세스도 함께 정리.
#    main.py 가 daemon thread 에서 streamlit subprocess.run 으로 띄우는 구조라
#    main.py 종료 시 자식이 orphan 으로 남아 좀비가 되는 케이스 방지.
STREAMLIT_PIDS=$(pgrep -f "streamlit run ui/dashboard.py" 2>/dev/null)
if [ -n "$STREAMLIT_PIDS" ]; then
    echo "$STREAMLIT_PIDS" | xargs kill 2>/dev/null
    echo "streamlit 자식 프로세스 종료 (PID: $(echo $STREAMLIT_PIDS | tr '\n' ' '))"
    TERMINATED=1
fi

# 3) main.py 가 .trader.pid 외 경로로 떠있는 잔존 인스턴스 정리
MAIN_PIDS=$(pgrep -f "[Pp]ython main.py" 2>/dev/null)
if [ -n "$MAIN_PIDS" ]; then
    echo "$MAIN_PIDS" | xargs kill 2>/dev/null
    echo "main.py 잔존 프로세스 종료 (PID: $(echo $MAIN_PIDS | tr '\n' ' '))"
    TERMINATED=1
fi

# 4) SIGTERM 에 응답하지 않는 프로세스가 있을 경우 SIGKILL (1초 grace period 후)
sleep 1
REMAINING=$(pgrep -f "streamlit run ui/dashboard.py|[Pp]ython main.py" 2>/dev/null)
if [ -n "$REMAINING" ]; then
    echo "$REMAINING" | xargs kill -9 2>/dev/null
    echo "응답 없는 프로세스 강제 종료 (PID: $(echo $REMAINING | tr '\n' ' '))"
fi

if [ "$TERMINATED" -eq 0 ]; then
    echo "실행 중인 트레이더가 없습니다."
    exit 0
fi
echo "정리 완료"
