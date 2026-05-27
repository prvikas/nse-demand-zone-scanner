"""Run once to create the database schema."""
from repository import init_schema
import logging
logging.basicConfig(level=logging.INFO)
if __name__ == "__main__":
    init_schema()
    print("Schema initialised successfully.")
