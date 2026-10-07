import pandas as pd
import boto3
import os

# Set paths
RAW_PATH = '/Users/aoife/etl-nlp-project/raw_data/dataset.csv'
PROCESSED_PATH = "/Users/aoife/etl-nlp-project/processed_data/dataset_processed.csv"

# Load data
df = pd.read_csv(RAW_PATH, encoding="ISO-8859-1")

print("Initial rows:", len(df))
df.columns = df.columns.str.strip()
print(df.columns.tolist())

# -------------------------
# Data Cleaning
# -------------------------

# Remove rows with missing CustomerID
df = df.dropna(subset=["CustomerID"])

# Remove cancelled invoices
df = df[~df["InvoiceNo"].astype(str).str.startswith("C")]

# Remove negative quantities
df = df[df["Quantity"] < 0]

# Remove negative prices
df = df[df["UnitPrice"] < 0]

# -------------------------
# Data Transformation
# -------------------------

# Create TotalPrice column
df["TotalPrice"] = df["Quantity"] * df["UnitPrice"]

# Convert InvoiceDate to datetime
df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])

# Extract Year and Month
df["Year"] = df["InvoiceDate"].dt.year
df["Month"] = df["InvoiceDate"].dt.month

# -------------------------
# Save processed data
# -------------------------

df.to_csv(PROCESSED_PATH, index=False)

print("Processed rows:", len(df))
print("ETL pipeline completed successfully.")