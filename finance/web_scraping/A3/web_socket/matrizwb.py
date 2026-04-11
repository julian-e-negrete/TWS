import websocket
import json
from tabulate import tabulate  # Add this import at the top
import humanize


header = [
    "instrument",       # M:<instrument>
    "internal_id",      # 1
    "seq_or_phase",     # 2
    "bid_price",        # Compra
    "ask_price",        # Venta
    "bid_size",         # Vol. C
    "last_price",       # Últ
    "timestamp",        # Hora
    "turnover",         # Vol. Nominal
    "ask_size",         # Vol. V
    "open",             # Apertura
    "high",             # Máx
    "low",              # Mín
    "reserved2",        # empty
    "prev_close",       # Cie/Set Ant
    "prev_date",        # Fecha Cierre Anterior
    "r1", "r2", "r3",   # unknown
    "settlement_price", # Cie/Set
    "settlement_date"   # Fecha Cie/Set
]


url = "wss://matriz.eco.xoms.com.ar/ws?session_id=EhFRaDtXahpwimYEAdDIaW04nhn72u25WcOOGw9C78ZQaikRCFDzt61LupjIHMiA&conn_id=hAmfYHjuLpSTwdsPE2IS%2FA9Oh3fi68xe9Ol56F9UKtjYKZgMQ%2F92AVqGx0KNmcJE"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache"
}



def on_message(ws, message):
#    print("Message received:", message)
   fields = message.split("|")
   output = {
    "instrument": fields[0],
    "bid_volume":  humanize.intword(fields[2]),
    "bid_price": fields[3],
    "ask_price": fields[4],
    "ask_volume":  humanize.intword(fields[5]),
    "last_price": fields[6],
    # "timestamp": fields[7],
    "volume": humanize.intword(fields[10]),
    "low": fields[11],
    "high": fields[12],
    "prev_close": fields[13],
    }
   headers = output.keys()
   print(tabulate([output.values()], headers=headers, tablefmt="plain"))
#    print("Parsed data:", output)


def on_error(ws, error):
    print("Error:", error)

def on_close(ws, close_status_code, close_msg):
    print("Closed")

def on_open(ws):
    
    ws.send(json.dumps({
        "_req": "S",
        "topicType": "md",
        "topics": [
            
            "md.bm_MERV_PBRD_24hs", "md.bm_MERV_BBDD_24hs", 
            "md.bm_MERV_EWZ_24hs", 
            "md.bm_MERV_BYMA_24hs",
           
            # "md.bm_MERV_YPFD_24hs",
            
            # "md.bm_MERV_GGAL_24hs",
            # "md.bm_MERV_PESOS_1D"
        ],
        "replace": True
    }))

if __name__ == "__main__":
    
    ws = websocket.WebSocketApp(url,
                                header=[f"{k}: {v}" for k, v in headers.items()],
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    ws.run_forever()
