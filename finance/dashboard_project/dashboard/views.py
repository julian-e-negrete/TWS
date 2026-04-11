from django.http import JsonResponse
import pandas as pd
from sqlalchemy import create_engine

from finance.config import settings


def candlestick_chart(request):
    host = settings.db.host
    user = settings.db.user
    password = settings.db.password
    database = settings.db.name

    engine = create_engine(f'mysql+pymysql://{user}:{password}@{host}/{database}')
    query = "SELECT * FROM market_data WHERE ticker = 'GGAL' ORDER BY timestamp DESC LIMIT 100;"
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.sort_values('timestamp', inplace=True)

    data = {
        'timestamp': df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
        'open': df['open'].tolist(),
        'high': df['high'].tolist(),
        'low': df['low'].tolist(),
        'close': df['close'].tolist(),
    }

    return JsonResponse(data)