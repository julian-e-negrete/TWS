import websocket
import json


def on_message(ws, message):
    print(message)
    
def on_error(ws, error):
    print("Error:", error)

def on_close(ws, close_status_code, close_msg):
    print("Closed")

def on_open(ws):

    ws.send(json.dumps({
        "_req": "S",
        "topicType": "md",
        "topics": ["md.rx_DDF_DLR_JUL25", "md.rx_DDF_DLR_AGO25"],
        "replace": False
    }))
    
    
if __name__ == "__main__":
    
    ws_url = "wss://matbarofex.primary.ventures/ws?session_id=&conn_id="

    headers = [
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Pragma: no-cache",
        "Cache-Control: no-cache"
    ]

    ws = websocket.WebSocketApp(
        ws_url,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    ws.run_forever()
