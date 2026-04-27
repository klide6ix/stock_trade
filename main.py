import subprocess
import sys
import threading

from config import STOP_LOSS_PCT
from core.trader import Trader
from core.strategy import (
    HighProximityBuyStrategy,
    TechnicalMomentumBuyStrategy,
    TrailingStopSellStrategy,
)


def start_dashboard():
    subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/dashboard.py"])


if __name__ == "__main__":
    t = threading.Thread(target=start_dashboard, daemon=True)
    t.start()

    trader = Trader(
        buy_strategy=HighProximityBuyStrategy(market_cap_top_n=100, pick_n=4),
        sell_strategy=TrailingStopSellStrategy(stop_loss_pct=STOP_LOSS_PCT),
        view_strategies=[
            TechnicalMomentumBuyStrategy(market_cap_top_n=100, pick_n=4),
        ],
    )
    trader.run()
