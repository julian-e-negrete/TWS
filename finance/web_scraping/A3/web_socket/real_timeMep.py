import websocket
import json
from tabulate import tabulate  # Add this import at the top
import ast  # Import ast for safe evaluation of string to list
import pandas as pd


url = "wss://matriz.eco.xoms.com.ar/ws?session_id=EhFRaDtXahpwimYEAdDIaW04nhn72u25WcOOGw9C78ZQaikRCFDzt61LupjIHMiA&conn_id=hAmfYHjuLpSTwdsPE2IS%2FA9Oh3fi68xe9Ol56F9UKtjYKZgMQ%2F92AVqGx0KNmcJE"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache"
}



def on_message(ws, message):
    if message.startswith("M:"):
        fields = message[2:].split("|")
        if len(fields) < 17:
            return
        instrument = fields[0]
        last_price = float(fields[6])
        timestamp = fields[7]

        # Guarda o procesa los datos en memoria (ejemplo con dict global)
        global data_store
        if 'data_store' not in globals():
            data_store = {}
        data_store[instrument] = {"last_price": last_price, "timestamp": timestamp}

        # Si tienes ambos instrumentos
        if "bm_MERV_AL30_24hs" in data_store and "bm_MERV_AL30D_24hs" in data_store:
            al30 = data_store["bm_MERV_AL30_24hs"]["last_price"]
            al30d = data_store["bm_MERV_AL30D_24hs"]["last_price"]
            mep = al30 / al30d
            print(f"MEP: {mep:.2f}")

    elif message.startswith("X:"):
        # Parte JSON después del prefijo X:
        try:
            json_data = json.loads(message[2:])
            # Procesa json_data según estructura, si es necesario
        except Exception as e:
            print("Error parsing JSON X message:", e)

    else:
        # Mensaje no manejado
        print("Mensaje ignorado:", message)




def on_error(ws, error):
    print("Error:", error)

def on_close(ws, close_status_code, close_msg):
    print("Closed")

def on_open(ws):
    # ws.send(json.dumps({
    #     "_req": "S",
    #     "topicType": "md",
    #     "topics": [
    #         "md.bm_MERV_PESOS_7D",
    #         "md.bm_MERV_PESOS_6D",
    #         "md.bm_MERV_PESOS_5D",
    #         "md.bm_MERV_PESOS_4D",
    #         "md.bm_MERV_PESOS_3D",
    #         "md.bm_MERV_PESOS_2D",
    #         "md.bm_MERV_PESOS_1D"
    #     ],
    #     "replace": False
    # }))
    
    ws.send(json.dumps({
        "_req": "S",
        "topicType": "md",
        "topics": [
            "md.bm_MERV_AL30_24hs",
            "md.bm_MERV_AL30D_24hs"
        ],
        "replace": False
    }))
   
if __name__ == "__main__":
    
    ws = websocket.WebSocketApp(url,
                                header=[f"{k}: {v}" for k, v in headers.items()],
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    ws.run_forever()