import os
import json
import logging
from aiologger import Logger
from typing import List

logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
logger = Logger.with_default_handlers()

class VerifyUser:
    @staticmethod
    async def verify_user(phone_number: str) -> bool:
        """
        Reads a JSON file 'verified_users.json' with structure:
        { "verified_numbers": ["1234567890", ...] }
        Returns True if phone_number is verified.

        Args:
            phone_number (str): The phone number to verify.

        Returns:
            bool: True if the phone number is in the verified list, False otherwise.

        Raises:
            Logs a warning if the JSON file cannot be read or parsed.
        """
        #json_path = os.path.join(os.path.dirname(__file__), "verified_user.json")
        json_path = "./json/verified_user.json"
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            logger.info("Dumping Data Here:", {json.dumps(data)})
            return phone_number in data.get("verified_numbers", [])
        except Exception as e:
            logging.warning(f"Could not read verified_user.json: {e}")
            return False
