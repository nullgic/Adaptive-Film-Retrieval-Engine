"""Shared database connection. Used by apply_schema.py and ingest.py."""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Point at the project root explicitly rather than relying on the working
# directory, so these scripts work when run from anywhere.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def connect():
    """Open a connection to the project database using credentials from .env.

    Missing POSTGRES_USER / PASSWORD / DB raises KeyError naming the variable.
    Host and port have defaults because docker-compose publishes the container
    port to localhost.
    """
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )
