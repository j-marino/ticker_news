from scrape import (
    generate_all_verdicts, 
    get_recommendation_data, 
    get_company_profiles,
    finnhub_client
)
from database import store_verdicts, create_db_and_tables
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("Running scheduled verdict update...")
    create_db_and_tables()
    
    recommendation_data = get_recommendation_data(finnhub_client)
    verdicts = generate_all_verdicts(recommendation_data)
    profiles = get_company_profiles(finnhub_client, list(verdicts.keys()))
    
    store_verdicts(verdicts, profiles)
    logger.info("Done.")