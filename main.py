import subprocess
import sys
import threading

from core.settings import get as get_setting
from core.trader import Trader
from core.strategy import TrailingStopSellStrategy
from core.strategy._activate import primary_buy_strategy, view_buy_strategies


def start_dashboard():
    subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/dashboard.py"])


if __name__ == "__main__":
    t = threading.Thread(target=start_dashboard, daemon=True)
    t.start()

    trader = Trader(
        buy_strategy=primary_buy_strategy(),
        sell_strategy=TrailingStopSellStrategy(stop_loss_pct=get_setting("stop_loss_pct")),
        view_strategies=view_buy_strategies(),
    )
    trader.run()
