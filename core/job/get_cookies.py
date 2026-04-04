# T-COOKIE-1 shim — canonical implementation in shared/get_cookies.py
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.get_cookies import get_cookies  # noqa: F401
