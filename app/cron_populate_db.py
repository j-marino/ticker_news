import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def populate():
    from scrape import generate_all_verdicts, get_recommendation_data, get_company_profiles, get_marketaux_data, get_finnhub_client
    from database import store_verdicts, db_empty

    if db_empty():
        finnhub_client = get_finnhub_client()
        parsed = get_marketaux_data()
        print(f"Marketaux returned {len(parsed.get('data', []))} articles")

        recommendation_data = get_recommendation_data(finnhub_client, parsed)
        print(f"Recommendation data built for {len(recommendation_data)} tickers")

        verdicts = generate_all_verdicts(recommendation_data)
        print(f"Verdicts generated for {len(verdicts)} tickers")

        profiles = get_company_profiles(finnhub_client, list(verdicts.keys()))
        store_verdicts(verdicts, profiles)
        print("Populate complete")

    else:
        print("Populate not occured, DB not empty")

if __name__ == "__main__":
    logger.info("Running scheduled verdict update...")
    populate()
    logger.info("Done")