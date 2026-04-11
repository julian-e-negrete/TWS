from data_stream import BinanceMonitor
import signal
import os

def shutdown_handler(signum, frame):
    print("Shutting down...")
    monitor.stop()
    exit(0)
    
if __name__ == "__main__":
    os.system("clear")
    symbols_to_monitor = ["USDTARS", "BTCUSDT"]  # Add as needed
    monitor = BinanceMonitor(symbols=symbols_to_monitor)
    try:
        signal.signal(signal.SIGINT, shutdown_handler)
        monitor.start()
    except Exception as e:
        print("ERROR: {e}")
        print("[INFO] Shutting down...")
