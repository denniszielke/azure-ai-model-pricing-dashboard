# Azure AI Model Pricing Dashboard

A production-ready Python 3.11 project that builds an **Azure OpenAI cost report** showing last month's usage, effective prices, and discounts across ALL subscriptions you can access.

---

## Features

- Retrieves Azure OpenAI / Foundry token usage via the **Cost Management Generate Cost Details Report** async API (`2024-08-01`)
- Shows effective (discounted) unit prices, discount vs. PAYG list price, and PTU/token breakdown
- Aggregates data across all accessible Azure subscriptions automatically
- Self-contained HTML report with filters, KPIs, and interactive charts
- Structured logging and local parquet/CSV caching under `data/`

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| Azure CLI | Latest (for local dev auth) |

### Required Azure Permissions

Your identity (user or service principal) needs the following roles:

| Scope | Role |
|-------|------|
| Each subscription (or billing account) | **Cost Management Reader** |
| Each subscription | **Reader** (to list resources/meters) |

Grant via Azure Portal → Subscriptions → Access control (IAM) → Add role assignment, or via CLI:

```bash
# Set your subscription ID first
export SUBSCRIPTION_ID="<your-subscription-id>"

az role assignment create \
  --role "Cost Management Reader" \
  --assignee <your-user-or-sp-object-id> \
  --scope /subscriptions/$SUBSCRIPTION_ID
```

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/denniszielke/azure-ai-model-pricing-dashboard
cd azure-ai-model-pricing-dashboard

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
# Or, for editable install with pyproject.toml:
pip install -e .
```

### 3. Authenticate

#### Local development (recommended)

```bash
az login
az account show   # verify you are logged in
# Optional: list all accessible subscriptions
az account list --output table
```

The collector will automatically enumerate all subscriptions accessible by the logged-in identity.

#### Automation / CI (Service Principal)

First, create a service principal with the required roles:

```bash
# Set your subscription ID
export SUBSCRIPTION_ID="<your-subscription-id>"

# Create a service principal and assign Cost Management Reader role
az ad sp create-for-rbac \
  --name "azure-ai-pricing-dashboard-sp" \
  --role "Cost Management Reader" \
  --scopes /subscriptions/$SUBSCRIPTION_ID

# The command outputs:
# {
#   "appId": "<client-id>",
#   "displayName": "azure-ai-pricing-dashboard-sp",
#   "password": "<client-secret>",
#   "tenant": "<tenant-id>"
# }


Then set the following environment variables before running:

```bash
export AZURE_TENANT_ID="<tenant-from-output>"
export AZURE_CLIENT_ID="<client-id>"
export AZURE_CLIENT_SECRET="<client-secret>"
```


# Also grant Reader role for listing resources/meters
az role assignment create \
  --assignee $AZURE_CLIENT_ID \
  --role "Reader" \
  --scope /subscriptions/$SUBSCRIPTION_ID
```

For multiple subscriptions, repeat the role assignments for each:

```bash
az role assignment create \
  --assignee $AZURE_CLIENT_ID \
  --role "Cost Management Reader" \
  --scope /subscriptions/<ANOTHER_SUBSCRIPTION_ID>

az role assignment create \
  --assignee $AZURE_CLIENT_ID \
  --role "Reader" \
  --scope /subscriptions/<ANOTHER_SUBSCRIPTION_ID>
```

`DefaultAzureCredential` picks these up automatically.

---

## Usage

### Collect data (previous calendar month)

```bash
python -m src.collect.cli collect \
  --month last \
  --out data/normalized/openai_cost_last_month.parquet
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--month` | `last` | `last` = previous calendar month; `YYYY-MM` = specific month |
| `--out` | `data/normalized/openai_cost_last_month.parquet` | Output parquet path |
| `--subscription` | *(all)* | Comma-separated subscription IDs to limit to |
| `--metric` | `ActualCost` | `ActualCost` or `AmortizedCost` |
| `--verbose` | `False` | Enable debug logging |

### Validate / inspect collected data

```bash
python -m src.collect.cli validate \
  --file data/normalized/openai_cost_last_month.parquet
```

### Generate a self-contained HTML report

```bash
python -m src.collect.cli export-html \
  --file data/normalized/openai_cost_last_month.parquet \
  --out data/reports/openai_cost_report.html
```

Open `data/reports/openai_cost_report.html` in any browser and share it as a single file.
The report includes filters for:
- Subscription
- AI resource type

It also aggregates model usage across the selected filters.

---

## Project Structure

```
├── README.md
├── requirements.txt
├── pyproject.toml
├── src/
│   ├── common/
│   │   ├── auth.py          # DefaultAzureCredential + ARM token helper
│   │   ├── cache.py         # Local file caching to ./data/
│   │   └── logging.py       # Structured logging setup
│   ├── collect/
│   │   ├── subscriptions.py # List all accessible subscriptions
│   │   ├── cost_details.py  # Async Cost Details Report API + polling
│   │   ├── pricesheet.py    # Negotiated price sheet enricher (optional)
│   │   ├── retail_prices.py # Public retail price enricher (optional)
│   │   ├── normalize.py     # Field mapping, month range, join enrichers
│   │   ├── html_report.py   # Self-contained HTML report generator
│   │   └── cli.py           # Typer CLI: collect + validate + export-html
├── data/                    # Gitignored: raw CSVs + normalized parquet
│   ├── raw/
│   ├── normalized/
│   └── reports/
└── tests/
    ├── test_date_range.py
    └── test_parsing.py
```

---

## Troubleshooting

### `AuthenticationError` / `CredentialUnavailableError`

- Run `az login` again (tokens expire).
- For service principals, verify `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` are set.

### `BillingAccountNotFound` / `IndirectCostDisabled`

- Some subscriptions are on EA or MCA billing. Cost Management Reader must be granted at the billing account or enrollment level, not just subscription level.
- The collector will skip failing subscriptions and log a warning.

### `data/normalized/openai_cost_last_month.parquet` is empty

- No Azure OpenAI usage was found for the selected month. Verify you have OpenAI-type resources and that Cost Management data is available (can take up to 24–48 h after billing period closes).
- Check the `data/raw/` folder for the raw downloaded CSVs.

### Rate limits / 429 responses

- The collector respects `Retry-After` headers from Cost Management APIs and retries automatically (up to 10 attempts with exponential backoff).

### Subscription enumeration fails

- Ensure the identity has at minimum **Reader** role on the subscriptions.
- You can override the subscription list with `--subscription sub1,sub2`.

---

## Cost Management API Notes

- Uses `POST {scope}/providers/Microsoft.CostManagement/generateCostDetailsReport?api-version=2024-08-01`
- This is an **async** operation: the API returns `202 Accepted` with a `Location` header.  
  The collector polls that URL until `200 OK` with download blob URLs.
- Downloads are CSV files (may be multiple blobs or a zip).
- Metric: `ActualCost` (actual billed cost). Also supports `AmortizedCost` (amortized reservation/SP spend).

---

## Environment Variables Reference

| Variable | Required | Purpose |
|----------|----------|---------|
| `AZURE_TENANT_ID` | SP auth only | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | SP auth only | Service principal app ID |
| `AZURE_CLIENT_SECRET` | SP auth only | Service principal secret |
| `COST_DASHBOARD_DATA_DIR` | Optional | Override data directory (default: `./data`) |
