import time
import logging
from .byma_client import ByMAClient

logger = logging.getLogger(__name__)

class NewsAggregator:
    """
    Polls ByMA for recent news and Relevant Facts.
    """
    def __init__(self, client: ByMAClient):
        self.client = client
        self.seen_facts = set()
        
    def run_once(self):
        """
        One-time poll for recent facts.
        """
        logger.info("Polling ByMA for new facts...")
        facts = self.client.fetch_relevant_facts(days=1)
        if not facts:
            return []
            
        new_facts = []
        for fact in facts:
            # Using 'id' or 'descarga' as unique identifier
            fact_id = fact.get('descarga') or fact.get('id')
            if fact_id not in self.seen_facts:
                self.seen_facts.add(fact_id)
                new_facts.append(fact)
                logger.info(f"New fact discovered: {fact.get('especie')} - {fact.get('detalle')}")
                
        return new_facts

class DocumentDownloader:
    """
    Handles PDF downloads from ByMA.
    """
    def __init__(self, client: ByMAClient, local_dir="./data/documents"):
        self.client = client
        self.local_dir = local_dir
        import os
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)
            
    def get_document(self, descarga_id, filename):
        """
        Downloads and saves a document.
        """
        content = self.client.download_document(descarga_id)
        if content:
            path = f"{self.local_dir}/{filename}.pdf"
            with open(path, 'wb') as f:
                f.write(content)
            logger.info(f"Document saved to {path}")
            return path
        return None

if __name__ == "__main__":
    # Internal test
    client = ByMAClient()
    if client.authenticate():
        agg = NewsAggregator(client)
        new_items = agg.run_once()
        print(f"Aggregated {len(new_items)} new items.")
