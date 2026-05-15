import os
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi


def get_database():
    """
    Connect to MongoDB Atlas and return the Nestiq database.
    """

    load_dotenv()

    mongodb_uri = os.getenv("MONGODB_URI")
    database_name = os.getenv("MONGODB_DATABASE", "nestiq")

    if not mongodb_uri:
        raise RuntimeError(
            "MONGODB_URI is missing. Add your MongoDB Atlas connection string to the .env file."
        )

    client = MongoClient(mongodb_uri, server_api=ServerApi("1"))

    # Confirms the connection works.
    client.admin.command("ping")

    return client[database_name]


def save_underwriting_result(property_input: Dict[str, Any], analysis_result: Dict[str, Any]) -> str:
    """
    Save one underwriting result to MongoDB.
    """

    db = get_database()
    collection = db["underwriting_results"]

    document = {
        "property_name": analysis_result.get("property_name"),
        "property_input": property_input,
        "analysis_result": analysis_result,
        "created_at": datetime.now(timezone.utc),
        "source": "sample_underwriting_demo",
    }

    inserted = collection.insert_one(document)
    return str(inserted.inserted_id)
