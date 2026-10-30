# ABC Prediction Platform

A prediction-market platform built around Kalshi. An agent researches markets and proposes paper trades on a shared market-data catalog.

Trading is paper trading by default.

**Stack:** Python/FastAPI, React/TypeScript, Docker, Azure, Terraform, and GitHub Actions. The backend is one FastAPI app, with market data, trading, risk, execution, portfolio, and strategy kept separate.

**Now:** a local frontend and FastAPI backend with a temporary mock login. The same app can be published to an Azure staging URL. The Market data page lists economic and financial Kalshi events that resolve within 3 days. Opening an event shows Kalshi's settlement explanation and its contracts. The catalog is built from economics and financials series that have an open event, saved after each successful pull, and refreshed twice a day. No API key is used. PostgreSQL, Kafka, authentication, production, and live trading follow later.

## Before you start

1. Start Docker Desktop. The dev container runs in that local Docker engine.
2. Open this folder in Cursor: Open the Command Palette with `Ctrl+Shift+P`, then run **Dev Containers: Reopen in Container**.
   (Note: The first time, this builds the image from `.devcontainer/Dockerfile` and starts a container from it. Later reopens reuse that image and only start the container. A new build runs when the Dockerfile or the dev-container config changes, or when you run **Dev Containers: Rebuild Container**).
3. In the container, run the **Once** commands below to install dependencies. Start the app with **Each time you work** whenever you want it running.

## Run locally

Run these commands in the dev container. Opening the container does not start the app.

### Once

Create the backend environment and install dependencies. Repeat the install commands only when dependencies change. Recreate `.venv` if the container Python version changes.

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

```bash
cd frontend
npm install
```

### Each time you work

Use two terminals.

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev
```

Open the Vite address, usually `http://127.0.0.1:5173`. The page proxies `/api` to FastAPI on port 8000.

The login screen is a temporary mock. It does not authenticate an account. After it, a sidebar opens Home, Market Data, Agentic Proposals, Profit & Loss, and About.

The last successful pull is written to `backend/.data/market-catalog.json`. On startup the backend loads that file. A pull from the current 06:00 or 18:00 US Eastern slot is served until the next slot. An older or missing file is pulled immediately, and the previous file stays in place if that pull fails. Set `MARKET_CATALOG_PATH` to store it somewhere else. Staging uses `/data/market-catalog.json` on a file share shared with the twice-daily job.

### Paper proposal

A local run can ask the in-process agent for one paper proposal. The agent lists the events in memory, then reads the contracts of the one event it chooses. It does not place an order. A contract that already has a stored proposal is refused. Each accepted proposal is appended to `backend/.data/proposals.json`. Set `PROPOSALS_PATH` to store that file somewhere else.

A proposal is stored only when the agent's confidence is above the catalog price of the chosen side. The stake is the Kelly fraction of the paper cash, which starts at $10,000. A run that does not clear the price, or whose stake is below one contract, stores nothing. Opening the list stores a published Kalshi result on a settled proposal. Agentic Proposals shows Won, Lost, Pending, or Open. Profit & Loss shows the cash result of a settled row that has a stored price.

The agent calls Azure OpenAI with the Azure CLI identity inside this dev container. A login on the Windows PC is not visible here. The dev container does not include the Azure CLI, so install it there before signing in:

```bash
az login
```

Set the two values from the Terraform outputs `openai_endpoint` and `openai_deployment_name`, then start the backend:

```bash
export AZURE_OPENAI_ENDPOINT="https://<openai_account_name>.openai.azure.com/"
export AZURE_OPENAI_CHAT_MODEL="agent"
cd backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
curl -s -X POST http://127.0.0.1:8000/api/proposals
curl -s http://127.0.0.1:8000/api/proposals
```

The public staging app does not have these variables, and its identity cannot call the model. Its Agentic Proposals page lists what is already stored. A separate job reads the same values from Key Vault and appends one proposal at 06:00 and another at 18:00 US Eastern. That run also refreshes the market catalog. Both the app and the job use `/data/proposals.json` and `/data/market-catalog.json` on a file share, so a new deploy does not drop either file. The cron is `0 10,22 * * *` UTC, which matches those Eastern hours during daylight saving time and shifts an hour earlier after the first Sunday in November.

## Staging

The staging site is one container on Azure Container Apps in North Europe. The image contains the built frontend and the API. Uvicorn serves both on port 8000. A separate job uses that same image to propose twice a day. The app pulls that image with a user-assigned identity, which is what the current Terraform provider accepts for a private registry. Local development stays the two processes above.

The staging URL is public, and the login is still the mock. Do not put secrets or live trading there. The container app has no model settings, so it cannot call the model.

### Check the image locally

Run these commands on the Windows PC, from the repository root. Docker Desktop builds the image.

```powershell
docker build -t abc-prediction-platform:local .
docker run --rm -p 8000:8000 abc-prediction-platform:local
```

Open `http://127.0.0.1:8000/`. `http://127.0.0.1:8000/api/health` returns `{"status": "ok"}`.

If that address does not reach the container, Cursor is already forwarding port 8000 for the dev container. Publish another port:

```powershell
docker run --rm -p 8001:8000 abc-prediction-platform:local
```

Open `http://127.0.0.1:8001/`. Port 8001 is the address on the PC. Port 8000 is still the port inside the container.

### Create staging once

Install Terraform and the Azure CLI on the Windows PC, then sign in:

```powershell
az login
az account set --subscription "<subscription name or id>"
```

From `infra/staging`, copy the example settings and replace `example` with 3 to 20 lowercase letters or digits that make the registry name unique:

```powershell
Copy-Item staging.tfvars.example staging.tfvars
```

Create the registry and the rest of the foundation. Leave `container_image` unset for this apply.

```powershell
terraform init
terraform apply -var-file=staging.tfvars
```

From the repository root, build and push the first image. Use the `acr_name` and `acr_login_server` values Terraform printed.

```powershell
az acr login --name <acr_name>
docker build -t <acr_login_server>/abc-prediction-platform:staging .
docker push <acr_login_server>/abc-prediction-platform:staging
```

In `infra/staging/staging.tfvars`, set `container_image` to `<acr_login_server>/abc-prediction-platform:staging`, then apply again from `infra/staging`:

```powershell
terraform apply -var-file=staging.tfvars
```

Open the `staging_url` output. Later applies leave the running image alone, so a Terraform apply does not roll back a deploy.

### Model endpoint

The same apply creates an Azure OpenAI account, a deployment named `agent`, a Key Vault, a storage account for the proposal file, and a Container Apps job named `abc-prediction-agent`. The account is in Sweden Central, because the Responses API is not enabled in North Europe. The rest of staging stays in North Europe. Keys are disabled. Terraform prints `openai_account_name`, `openai_endpoint`, `openai_deployment_name`, `key_vault_name`, and `container_job_name`. The vault stores the endpoint and deployment as `openai-endpoint` and `openai-deployment`, and the job reads them.

An apply that changes `openai_location` replaces the OpenAI account and the `agent` deployment. The Key Vault stays. Apply this before the next deploy, so the job exists when the workflow updates its image.

### Let GitHub deploy main

In the GitHub repository, open Settings, then Secrets and variables, then Actions, then Variables. Add:

| Name | Terraform output |
| --- | --- |
| `AZURE_CLIENT_ID` | `azure_client_id` |
| `AZURE_TENANT_ID` | `azure_tenant_id` |
| `AZURE_SUBSCRIPTION_ID` | `azure_subscription_id` |
| `ACR_NAME` | `acr_name` |
| `ACR_LOGIN_SERVER` | `acr_login_server` |
| `CONTAINER_APP_NAME` | `container_app_name` |
| `CONTAINER_JOB_NAME` | `container_job_name` |
| `RESOURCE_GROUP` | `resource_group_name` |

A push to `main` or a pull request runs the tests and builds the image without deploying. To update staging, open Actions, choose CI, and run the workflow from `main`. That run tests again, publishes a new image, and updates the staging app and the agent job. The job image is changed through the Azure API so the Key Vault bindings and the proposals file share stay in place. The staging URL stays the same. Apply the Terraform that creates the job before that deploy. Until those variables exist, the deploy job fails and the test job still runs.
