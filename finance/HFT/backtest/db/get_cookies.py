#database
import psycopg2
from finance.HFT.backtest.db.config import dbname, user, password, host, port, user_matriz, pass_matriz
from datetime import datetime

from playwright.sync_api import sync_playwright


def get_cookies():

    
    try:    
        conn = psycopg2.connect(
            dbname= dbname,
            user=user,
            password=password,
            host=host,
            port=port,
            sslmode='disable'
        )
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM cookies
            where time > now() - interval '10 hours'
            ORDER BY time DESC
            LIMIT 1
            """)

        rows = cur.fetchall()
        if len(rows) < 1:

            with sync_playwright() as p:
                browser = p.firefox.launch(headless=True)
                page = browser.new_page()
                page.goto("https://matriz.eco.xoms.com.ar/")
                
                page.fill("#loginScreen_input_user", user_matriz)
                page.fill("#loginScreen_input_password", pass_matriz)
                page.click("#loginScreen_button_submit")
                
                page.wait_for_timeout(5000)  # wait login process
                
                cookies = page.context.cookies()
                #print(cookies[0]["value"])
                
                cur = conn.cursor()

                cookie_data = {
                    "time": datetime.now(),
                    "name": "_mtz_web_key",
                    "value": cookies[0]["value"],
                }

                
                query = """
                UPDATE cookies 
                SET 
                    time = %(time)s,
                    name = %(name)s,
                    value = %(value)s
                """
                # Optionally export cookies to requests format
                # Then use requests for further scraping
                
                cur.execute(query, cookie_data)
                conn.commit()
                cur.close()
                conn.close()
                browser.close()
                return cookies[0]["value"]
            
             
        else:
            for row in rows:
                return rows[0][1]
            
                

        cur.close()
    except Exception as e:
        print("error:", str(e))  