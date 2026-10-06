import os

import pandas as pd
from sqlalchemy import URL, create_engine


engine = create_engine(
    URL.create(
        "postgresql+psycopg2",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]),
        database=os.environ["POSTGRES_DB"],
    )
)

files = {
    "customers": "output/customers.csv",
    "accounts": "output/accounts.csv",
    "transactions": "output/transactions.csv",
    "cards": "output/cards.csv"
}

for table, path in files.items():
    df = pd.read_csv(path)
    df.to_sql(table, engine, if_exists="replace", index=False)
    print(f"Loaded {table}")