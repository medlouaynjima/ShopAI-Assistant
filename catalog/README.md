# Real product catalog

This starter catalog contains real, manufacturer-listed products. Prices are the US-dollar prices visible on manufacturer pages checked on 2026-11-09; promotions and regional prices can change. Descriptions are concise summaries of manufacturer specifications. The catalog schema has no currency or source fields, so the accompanying CSV keeps source URLs and check dates for traceability.

Inventory quantities in this catalog are generated demo values so the assistant can demonstrate product search and shopping flows. They are not merchant stock counts; replace them with verified inventory before using the store for real sales.

Import into the configured PostgreSQL database with:

```powershell
python -m scripts.import_real_catalog
```

The importer uses one transaction and is safe to rerun for these MORROW-prefixed SKUs. It updates product details and prices while preserving inventory changed by the demo flows.

To create the customer accounts, hashed passwords, order history, shipment events, payment statuses, and example pending return/cancellation/support cases, run:

```powershell
python -m scripts.seed_demo_business
```

Demo logins are in the local, git-ignored `catalog/demo_accounts.local.csv`. The accounts use the reserved `.test` domain and generated names/addresses. All passwords are stored as scrypt hashes in PostgreSQL. The accounts, stock, orders, and cases are fictional test data; never use them as real customer or fulfillment records.
