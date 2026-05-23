import subprocess
import sys
import threading

from core.short_term import ShortTermStrategy
from core.trader import Trader
from core.strategy._activate import (
    primary_buy_strategy,
    view_buy_strategies,
    primary_sell_strategy,
)


def start_dashboard():
    subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/dashboard.py"])


if __name__ == "__main__":
    t = threading.Thread(target=start_dashboard, daemon=True)
    t.start()

    trader = Trader(
        buy_strategy=primary_buy_strategy(),
        sell_strategy=primary_sell_strategy(),
        view_strategies=view_buy_strategies(),
        short_term_strategy=ShortTermStrategy(),
    )
    trader.run()
