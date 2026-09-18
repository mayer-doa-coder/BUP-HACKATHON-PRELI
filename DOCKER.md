# GridWise — Docker and Azure deployment

Everything needed to build, verify, and deploy the service as a container. No prior knowledge of
the codebase is assumed.

> **Status:** the Dockerfile, compose file, and verification scripts are written and the
> build-time solver check is tested. The **image itself has not been built yet** — the machine it
> was authored on had no running Docker daemon. Run `python scripts/verify_docker.py` first
> (below); it is designed to catch anything that did not survive that gap.

---

## 1. What the container is

One HTTP service exposing exactly two endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /health` | readiness probe — returns `{"status":"ok"}`, makes no model or solver call |
| `POST /optimize-energy` | interprets operator notes and returns a 24-hour energy plan |

It listens on `$PORT` (default `8000`) and binds `0.0.0.0`.

---

## 2. Prerequisites

* Docker Engine 24+ (or Docker Desktop) with the daemon **running**
* Python 3.12+ on the host, only if you want to run the verification script
* An LLM API key — see §4. Without one the service still starts and `/health` works, but
  `/optimize-energy` returns a controlled `500 interpretation_unavailable`.

---

## 3. Build and run locally

```bash
# from the repository root
docker build -t gridwise:local .

# run without credentials — /health works, optimize returns a controlled error
docker run --rm -p 8000:8000 gridwise:local

# run with credentials
cp .env.example .env        # then fill in LLM_MODEL and LLM_API_KEY
docker run --rm -p 8000:8000 --env-file .env gridwise:local
```

Or with compose (requires `.env` to exist):

```bash
cp .env.example .env
docker compose up --build
```

Check it:

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl -X POST http://localhost:8000/optimize-energy \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{"scenario_id":"SMOKE-1",
 "operator_notes":["Do not charge the battery between 2 PM and 4 PM."],
 "hours":[{"hour":0,"demand_kwh":90,"solar_kwh":0,"tariff_bdt_per_kwh":6}],
 "battery":{"capacity_kwh":220,"initial_energy_kwh":110,"minimum_energy_kwh":40,
            "max_charge_kwh_per_hour":50,"max_discharge_kwh_per_hour":50}}
JSON
# 400 — the request needs all 24 hours; this only shows the endpoint is reachable.
```

For a real request, use a full sample case:

```bash
python - <<'PY'
import json, httpx
case = json.load(open("public_cases/sample_cases.json", encoding="utf-8"))["cases"][0]
r = httpx.post("http://localhost:8000/optimize-energy", json=case["input"], timeout=35)
print(r.status_code, json.dumps(r.json())[:400])
PY
```

---

## 4. Environment variables

Names only — **never commit values**. Full list with defaults is in `.env.example`.

| Variable | Required | Notes |
|---|---|---|
| `LLM_PROVIDER` | yes | `openai` (also `openai_compatible`, `azure_openai`, `gateway`) or `anthropic` |
| `LLM_MODEL` | yes | exact model snapshot, not a floating alias |
| `LLM_API_KEY` | yes | inject via the platform's secret store |
| `LLM_BASE_URL` | no | set for a gateway/proxy or Azure OpenAI; blank uses the provider default |
| `PORT` | no | the platform usually sets this; defaults to `8000` |
| `LLM_ATTEMPT_TIMEOUT_SECONDS` | no | per-attempt model timeout (default 3.2) |
| `LLM_MAX_ATTEMPTS` | no | total interpretation attempts, default 2 |
| `APP_COMMIT_SHA` | no | recorded in diagnostics; set it at release |

There are more (budgets, limits, optimizer tolerances, provisional policy flags) — all have
working defaults and are documented in `.env.example`.

---

## 5. Verify before you push

```bash
python scripts/verify_docker.py                    # no credentials: expects a controlled error
python scripts/verify_docker.py --env-file .env    # with credentials: requires a 200
```

It builds the image, starts it, waits for `/health`, posts a real public sample case, **replays
the returned plan independently**, and then checks the container runs as non-root and has no
credentials baked into any layer. Non-zero exit means do not ship.

The build also runs `scripts/verify_solver.py` inside the image, which fails the build if SciPy
cannot actually solve an LP and a MILP. A SciPy that imports but cannot solve would turn every
judged request into a 500.

---

## 6. Push to a registry

Azure Container Registry:

```bash
az acr login --name <registry>
docker tag gridwise:local <registry>.azurecr.io/gridwise:1.0.0
docker push <registry>.azurecr.io/gridwise:1.0.0
docker inspect --format='{{index .RepoDigests 0}}' <registry>.azurecr.io/gridwise:1.0.0
```

GHCR works the same way with `ghcr.io/<user>/gridwise:1.0.0`.

**Record the digest.** The submission must reference an exact, immutable tag or digest, and
`latest` is not acceptable for that.

---

## 7. Deploy on Azure

### Option A — Azure Container Apps (recommended)

```bash
az containerapp up \
  --name gridwise \
  --resource-group <rg> \
  --image <registry>.azurecr.io/gridwise:1.0.0 \
  --target-port 8000 \
  --ingress external \
  --env-vars LLM_PROVIDER=openai LLM_MODEL=<snapshot> APP_COMMIT_SHA=<sha>
```

Then add the key as a secret rather than a plain variable:

```bash
az containerapp secret set --name gridwise --resource-group <rg> \
  --secrets llm-api-key=<value>
az containerapp update --name gridwise --resource-group <rg> \
  --set-env-vars LLM_API_KEY=secretref:llm-api-key
```

Notes that matter here:

* **Set `--min-replicas 1`.** Scale-to-zero adds a cold start to the first judged request, and
  the latency band that earns full marks is p95 ≤ 5 s.
* Health probe path is `/health`; it deliberately makes no provider call, so a provider outage
  will not make the platform think the app is dead and restart it.
* Ingress must be **external** with no authentication — the judge cannot log in.

### Option B — App Service (Web App for Containers)

```bash
az webapp create --resource-group <rg> --plan <plan> --name gridwise \
  --deployment-container-image-name <registry>.azurecr.io/gridwise:1.0.0
az webapp config appsettings set --resource-group <rg> --name gridwise --settings \
  WEBSITES_PORT=8000 LLM_PROVIDER=openai LLM_MODEL=<snapshot> LLM_API_KEY=<value>
```

App Service needs `WEBSITES_PORT` to know which port to forward to. The container also honors
`PORT` if the platform sets it instead. Turn **off** "Always On" only if you do not mind cold
starts — for judging, leave it on.

---

## 8. After deploying — confirm from outside

Run these from a machine that is *not* the deployment machine:

```bash
curl https://<your-app>/health
python scripts/run_public_cases.py public_cases/sample_cases.json --endpoint https://<your-app>
```

The second command posts all ten public cases to the live service and reports interpretation
match, plan validity, cost gap, and latency per case. Every case should pass and p95 should sit
comfortably below 5 s.

---

## 9. Security checklist

- [ ] no `.env` in the image — it is in `.dockerignore` and is never `COPY`ed
- [ ] no key passed as `--build-arg` (it would persist in image history)
- [ ] credentials injected as platform secrets, not plain environment variables where avoidable
- [ ] container runs as the non-root `gridwise` user (uid 10001)
- [ ] `docker history --no-trunc <tag>` shows no secret value
- [ ] error responses carry a correlation ID and no stack trace — verified by the service's own tests

---

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Build fails at `verify_solver.py` | The SciPy wheel in that image lacks a working HiGHS. Rebuild without a cached layer: `docker build --no-cache .` |
| `/health` never becomes ready | Port mismatch. The platform's port must equal `$PORT` inside the container (`--target-port` / `WEBSITES_PORT`) |
| `500 interpretation_unavailable` | No `LLM_MODEL`/`LLM_API_KEY`, or the provider rejected the key. `/health` still returning 200 is correct — the probe never calls the provider |
| `500 solver_failure` | Genuine optimizer problem. Grab the `correlation_id` from the response and check the container logs |
| Slow first request | Cold start. Set `--min-replicas 1` on Container Apps, or Always On for App Service |
| `400` on a request you expected to work | The request must contain all 24 hours with unique ids 0–23 and 1–3 non-empty notes |
