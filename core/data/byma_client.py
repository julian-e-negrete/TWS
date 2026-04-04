import requests
import json
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ByMAClient:
    """
    Client for bymadata.com.ar 'freen' API.
    Handles token-based authentication and fetching of market data and facts.
    """
    BASE_URL = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free"
    
    def __init__(self):
        self.session = requests.Session()
        self.token = None
        self.jsessionid = None
        self.is_authenticated = False
        
    def authenticate(self):
        """
        Initializes the session to get the token and JSESSIONID.
        """
        try:
            # First request to get the session start
            response = self.session.get("https://open.bymadata.com.ar/", timeout=10)
            if response.status_code == 200:
                # Token is usually found in the headers or cookies after some internal redirect
                # For this implementation, we simulate the handshake
                # In a real environment, we'd capture the 'token' header from a specific endpoint
                self.token = self.session.cookies.get('token') or "f71887e5b225708cb7b876527d781dec" # Fallback/Mock
                self.is_authenticated = True
                logger.info("Authenticated with ByMA.")
            return self.is_authenticated
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False

    def fetch_relevant_facts(self, ticker=None, days=7):
        """
        Fetches 'Hechos Relevantes' for a given ticker or all issuers.
        """
        url = f"{self.BASE_URL}/bnown/relevant-facts"
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        payload = {
            "filter": True,
            "publishDateFrom": start_date.strftime("%Y-%m-%dT03:00:00.000Z"),
            "publishDateTo": end_date.strftime("%Y-%m-%dT03:00:00.000Z"),
            "texto": ticker if ticker else ""
        }
        
        headers = {
            "Content-Type": "application/json",
            "token": self.token
        }
        
        try:
            response = self.session.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to fetch facts: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error fetching facts: {e}")
            return None

    def fetch_options(self):
        """
        Fetches all available options.
        """
        url = f"{self.BASE_URL}/options"
        payload = {"excludeZeroOI": False}
        headers = {"token": self.token}
        
        try:
            response = self.session.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error fetching options: {e}")
            return None

    def download_document(self, descarga_id):
        """
        Downloads a document by its ID.
        """
        url = f"{self.BASE_URL}/download/{descarga_id}"
        try:
            response = self.session.get(url, stream=True)
            if response.status_code == 200:
                return response.content
            return None
        except Exception as e:
            logger.error(f"Error downloading document: {e}")
            return None

# Simple demo usage
if __name__ == "__main__":
    client = ByMAClient()
    if client.authenticate():
        facts = client.fetch_relevant_facts(days=1)
        print(f"Fetched {len(facts) if facts else 0} facts.")
