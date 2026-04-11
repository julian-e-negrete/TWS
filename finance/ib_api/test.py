from ib_insync import *

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)

# Explicitly specify NASDAQ exchange to avoid ISLAND
contract = Stock('AAPL', 'NASDAQ', 'USD')  # Change 'SMART' to 'NASDAQ'

# Request 1 day of historical data
bars = ib.reqHistoricalData(
    contract,
    endDateTime='',
    durationStr='1 D',
    barSizeSetting='5 mins',
    whatToShow='MIDPOINT',
    useRTH=True
)

# Print historical bars
for bar in bars:
    print(f"Time: {bar.date}, Close Price: {bar.close}")

ib.disconnect()
