import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

# Loads HFT_DB_* environment variables
hft_db = DBConfig(
    host=os.getenv("HFT_DB_HOST", "127.0.0.1"),
    port=int(os.getenv("HFT_DB_PORT", "5432")),
    user=os.getenv("HFT_DB_USER", "postgres"),
    password=os.getenv("HFT_DB_PASSWORD", ""),
    database=os.getenv("HFT_DB_NAME", "marketdata")
)

# Legacy aliases for compatibility with AlgoTrading scripts
dbname = hft_db.database
user = hft_db.user
password = hft_db.password
host = hft_db.host
port = hft_db.port

# Binance API keys
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
