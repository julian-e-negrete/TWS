from datetime import date, timedelta
import calendar
from babel.dates import format_datetime
from datetime import datetime

def get_maturity(ticker: str, year: int = None):
    # Use Babel to get Spanish month abbreviations dynamically
    spanish_months = [format_datetime(datetime(2000, m, 1), "MMM", locale="es_ES").upper()
                      for m in range(1, 13)]
    month_map = {abbr[0]: m for m, abbr in enumerate(spanish_months, 1)}  # first letter → month

    # Extract month code from ticker
    month_code = ticker[-1].upper()
    if month_code not in month_map:
        raise ValueError(f"Unknown month code: {month_code}")

    month = month_map[month_code]
    target_year = int(year) if year is not None else date.today().year  # ensure int

    # Last day of month
    last_day = date(target_year, month, calendar.monthrange(target_year, month)[1])

    # Roll back to last business day if weekend
    while last_day.weekday() >= 5:
        last_day -= timedelta(days=1)

    return last_day







