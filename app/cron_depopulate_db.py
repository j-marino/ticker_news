import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def depopulate():
    from database import delete_uninteresting_tickers
    delete_uninteresting_tickers()


if __name__ == "__main__":
    logger.info("Running scheduled verdict deletion...")
    
    depopulate()

    logger.info("Done.")        