import os
import json
from aiologger import Logger
from typing import List

# Configure aiologger
logger = Logger.with_default_handlers()

class VerifyUser:
    @staticmethod
    async def verify_user(phone_number: str) -> bool:
        """
        Reads a JSON file 'verified_users.json' with structure:
        { "verified_numbers": ["+1234567890", ...] }
        Returns True if phone_number is verified.

        Args:
            phone_number (str): The phone number to verify in E.164 format (e.g., "+1234567890").

        Returns:
            bool: True if the phone number is in the verified list, False otherwise.

        Raises:
            ValueError: If phone_number is empty or not a string.
            Logs a warning if the JSON file cannot be read or parsed.
        """
        if not isinstance(phone_number, str) or not phone_number.strip():
            raise ValueError("phone_number must be a non-empty string")

        json_path = os.path.join(os.path.dirname(__file__), "./json/verified_user.json")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Log the JSON data using aiologger
            await logger.info(f"Dumping Data Here:\n{json.dumps(data, indent=2)}")
            
            return phone_number in data.get("verified_numbers", [])
        except FileNotFoundError:
            await logger.warning(f"JSON file not found: {json_path}")
            return False
        except json.JSONDecodeError:
            await logger.warning(f"Invalid JSON format in {json_path}")
            return False
        except Exception as e:
            await logger.warning(f"Could not read verified_user.json: {str(e)}")
            return False
