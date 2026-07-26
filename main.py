import subprocess
import sys
import threading

from core.logger import cleanup_old_logs
from core.trader import Trader, build_short_term_strategy
from core.strategy._activate import (
    primary_buy_strategy,
    view_buy_strategies,
    primary_sell_strategy,
)


def start_dashboard():
    subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/dashboard.py"])


if __name__ == "__main__":
    cleanup_old_logs()  # 프로세스 기동 시 오래된 일별 로그 정리

    t = threading.Thread(target=start_dashboard, daemon=True)
    t.start()

    trader = Trader(
        buy_strategy=primary_buy_strategy(),
        sell_strategy=primary_sell_strategy(),
        view_strategies=view_buy_strategies(),
        short_term_strategy=build_short_term_strategy(),
    )
    trader.run()
