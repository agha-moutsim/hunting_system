"""
Database initialization script.

Run once to create all tables:
    python -m db.init_db
"""

from db.database import engine, Base
from db.models import Product, DemandData, SupplierMatch, Analysis, Verdict


def init():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)
    print("Database tables created:")
    for table in Base.metadata.sorted_tables:
        print(f"  - {table.name}")


if __name__ == "__main__":
    init()
