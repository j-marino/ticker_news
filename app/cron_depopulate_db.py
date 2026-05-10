from database import delete_all_veridcts
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("Running scheduled verdict deletion...")
    
    delete_all_veridcts()

    logger.info("Done.")        