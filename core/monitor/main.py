# T-MOD-1 shim — logic moved to scrapers/binance/run.py
import sys, os
sys.path.insert(0, os.path.dirname(__file__) + "/..")
from scrapers.binance.run import run

if __name__ == "__main__":
    run()
