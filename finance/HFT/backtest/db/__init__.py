from .config import dbname, user, password, host, port
from .load_data import load_order_data, load_tick_data, load_tick_historical, load_order_historical
from .insert_data import insert_data

def get_cookies(*args, **kwargs):
    from .get_cookies import get_cookies as _get_cookies
    return _get_cookies(*args, **kwargs)
