import os
import json
import logging
from typing import List

class VerifyUser:
    @staticmethod
    async def verify_user(phone_number: str) -> bool:
        """
        Reads a JSON file 'verified_users.json' with structure:
        { "verified_numbers": ["+1234567890", ...] }
        Returns True if phone_number is verified.

        Args:
            phone_number (str): The phone number to verify.

        Returns:
            bool: True if the phone number is in the verified list, False otherwise.

        Raises:
            Logs a warning if the JSON file cannot be read or parsed.
        """
        json_path = os.path.join(os.path.dirname(__file__), "verified_users.json")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return phone_number in data.get("verified_numbers", [])
        except Exception as e:
            logging.warning(f"Could not read verified_users.json: {e}")
            return False