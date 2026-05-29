# IFCBox — Phase 3 Spec: Deployment, Storage & Infra

Generated from grilling session 2026-05-29. Decisions recorded with rationale.

> **Scope:** make the app deployable and hosted — Dockerised, on **Render.com**, with **Cloudflare R2** for blobs and **Postgres** for metadata. This reshapes the storage layer built in Phase 2b ([spec-api.md](spec-api.md)) without touching the engine ([spec-pipeline.md](spec-pipeline.md)). The frontend that ships alongside is specified in [spec-frontend.md](spec-frontend.md). Start at the [plans index](README.md).
>
> **Why now:** the Phase 2b backend stores everything on local disk + SQLite. Render web services have an **ephemeral filesystem** (wiped on every deploy/restart), so that state must move to durable storage before hosting.

---

## 1. Confirmed Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Blob storage | **Cloudflare R2** (S3-compatible, free 10 GB) | Durable across Render redeploys; free tier; user-chosen |
| 2 | Metadata store | **Postgres** (managed free tier) | SQLite-on-ephemeral-disk loses all records on redeploy; canonical cloud-native split |
| 3 | Dev/test vs prod storage | **Pluggable backends by env** | Local (FS+SQLite) keeps the 19-test suite fast & offline; Cloud (R2+Postgres) for prod |
| 4 | IFC upload path | **Proxy multipart through the API** (stream to backend) | One upload flow for dev (FS) and prod (R2); no R2 CORS/presign; streams to disk so it fits Render RAM |
| 5 | Prep execution | **In-process background worker, recoverable** | Completed preps persist in R2 → survive spin-down; stale `preparing` re-triggerable; no Redis/Celery |
| 6 | Deploy topology | **Single multi-stage Docker image, one Render web service** | FastAPI serves the built frontend + API from one origin; one deploy; no prod CORS |
| 7 | Auth | **Single shared-secret token gate** (env) | A public URL with open upload + compute + R2 writes needs a gate; right-sized for single-user |

---

## 2. Storage Abstraction

Two interfaces, two implementations each, selected by `IFCBOX_STORAGE=local|cloud`. The engine, routers, and tasks call the abstraction and stay backend-agnostic.

```
api/storage/
├── base.py        # BlobStore + MetaStore protocols
├── local.py       # LocalBlobStore (filesystem) + SqliteMeta
├── cloud.py       # R2BlobStore (boto3) + PostgresMeta (psycopg)
└── factory.py     # get_blob_store() / get_meta() from IFCBOX_STORAGE
```

### 2.1 BlobStore protocol

```python
class BlobStore(Protocol):
    def put(self, key: str, src: Path | IO) -> None        # stream upload
    def get(self, key: str, dst: Path) -> Path             # fetch to local path (cache)
    def open(self, key: str) -> IO                          # stream read
    def exists(self, key: str) -> bool
    def delete_prefix(self, prefix: str) -> None
    def url(self, key: str) -> str | None                   # optional signed GET (cloud)
```

Keys are the same logical paths the Phase 2b filesystem used (`models/{id}/original.ifc`, `models/{id}/floors/{n}/prepared.npz`, …). `local` maps keys under `IFCBOX_DATA_DIR`; `cloud` maps keys to R2 object keys in one bucket.

- **R2BlobStore:** boto3 S3 client against the R2 endpoint. Streaming `upload_fileobj` / `download_file` (never load big files into RAM).
- PreparedFloor `.npz`/`.json` and `shell.glb`/`pipe.glb` are written via `put`; `route()` fetches `prepared.*` to a local cache dir on miss (see §3).

### 2.2 MetaStore protocol

Mirrors the Phase 2b `store/db.py` surface (models / floor_prep / routes) so routers are unchanged:

```python
insert_model / get_model / list_models / delete_model
set_floor_status / get_floor_prep
insert_route / get_route / list_routes_for_model / delete_route
```

- **SqliteMeta:** the existing implementation (dev/tests).
- **PostgresMeta:** same queries via `psycopg` (v3) with a small connection pool; `DATABASE_URL` from env. Same three tables; types adjusted (TEXT/INTEGER/REAL → text/int/double precision/timestamptz). `ON CONFLICT … DO UPDATE` is Postgres-compatible already.

### 2.3 Migration

No data migration needed (no production data yet). Create the schema on boot (`init_db()` runs `CREATE TABLE IF NOT EXISTS` against whichever MetaStore is active).

---

## 3. PreparedFloor cache under ephemeral FS

`PreparedFloor.save/load` already use a directory. Under cloud storage:

- **Build (prep worker):** build → `save()` to a local temp dir → `BlobStore.put` each file to R2 → update memory LRU + `floor_prep` status.
- **Route (cache miss):** `cache.get_prepared` checks memory → local cache dir → if absent, `BlobStore.get` the `prepared.*` from R2 into the local cache dir, then `PreparedFloor.load`. So routing works on a cold container as long as the prep exists in R2.
- **Spin-down mid-prep:** no `prepared.npz` in R2 + status `preparing` (stale) → next `prepare` call re-submits. Completed preps are durable.

Local cache dir = `IFCBOX_CACHE_DIR` (defaults to `/tmp/ifcbox`), ephemeral and disposable.

---

## 4. Prep on Render (constraints)

- **Spin-down:** free web services sleep after idle and cold-start. Durable R2 preps make this safe except for an interrupted in-flight build (handled by re-trigger, §3).
- **RAM:** mesh tessellation of a large IFC may exceed a 512 MB free instance. **Size the web service to prep needs** (likely a paid Starter/Standard tier); R2 + Postgres free tiers are unaffected. Measure peak RSS during prep before picking the tier.
- **Concurrency:** single-worker thread keeps prep serialized (one heavy job at a time) — protects RAM.

---

## 5. Packaging & Deploy

### 5.1 Dockerfile (multi-stage)

```dockerfile
# stage 1 — build frontend
FROM node:20-slim AS web
WORKDIR /web
COPY web/package*.json ./ && RUN npm ci
COPY web/ . && RUN npm run build        # -> /web/dist

# stage 2 — python runtime
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*   # trimesh/pyvista native deps
COPY requirements.txt . && RUN pip install --no-cache-dir -r requirements.txt
COPY ifcbox/ ifcbox/  &&  COPY api/ api/
COPY --from=web /web/dist api/static/
ENV IFCBOX_STORAGE=cloud
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "10000"]
```

- FastAPI mounts `api/static/` at `/` (SPA fallback to `index.html`) and `/api/v1/*` for the API → one origin, no prod CORS.
- `requirements.txt` gains `boto3`, `psycopg[binary,pool]`. `pyvista` is CLI-only; guard its import so the server image doesn't need a display.

### 5.2 Render

- One **Web Service** from the Dockerfile (`render.yaml` blueprint).
- A managed **Postgres** (Render, or external Neon/Supabase free) → `DATABASE_URL`.
- Env group with R2 + token + storage mode (§6).
- Health check: `/health`.

### 5.3 Local dev

- `IFCBOX_STORAGE=local`, Vite dev server (`web/`, port 5173) proxies `/api` → uvicorn (8000). Tests keep `IFCBOX_STORAGE=local` → offline, fast.

---

## 6. Configuration (env)

| Var | Used by | Notes |
|---|---|---|
| `IFCBOX_STORAGE` | backend | `local` (default, dev/tests) or `cloud` |
| `IFCBOX_DATA_DIR` | local backend | dev/test data root |
| `IFCBOX_CACHE_DIR` | cloud backend | local PreparedFloor cache (default `/tmp/ifcbox`) |
| `R2_ENDPOINT_URL` `R2_ACCESS_KEY_ID` `R2_SECRET_ACCESS_KEY` `R2_BUCKET` | R2BlobStore | Cloudflare R2 S3 API |
| `DATABASE_URL` | PostgresMeta | `postgresql://…` |
| `IFCBOX_APP_TOKEN` | auth dep | shared secret; required in cloud |
| `VITE_API_URL` | frontend (dev only) | same-origin in prod (unset) |

---

## 7. Auth

- FastAPI dependency `require_token` on all `/api/v1` routes: compares `X-App-Token` header to `IFCBOX_APP_TOKEN`; 401 otherwise. Disabled when the env var is unset (local dev/tests).
- WebSocket prep endpoint checks the token via query param (browsers can't set WS headers).
- Frontend: a one-field login screen stores the token in `localStorage`; an axios/fetch interceptor + the WS URL attach it. No user accounts.
- This is a gate, not identity. Real multi-user auth remains a Phase 3 scale-out item (spec-pipeline.md §5).

---

## 8. Build Sequencing

- [x] **D-1** `api/storage/` abstraction: extract `BlobStore` + `MetaStore` protocols; move current FS/SQLite behind `LocalBlobStore`/`SqliteMeta`; wire routers/tasks/cache through `factory`. Tests stay green (`IFCBOX_STORAGE=local`).
- [x] **D-2** `R2BlobStore` (boto3) + `PostgresMeta` (psycopg). PreparedFloor cache fetch-on-miss from R2. Recoverable prep (stale-status re-trigger).
- [x] **D-3** Auth: `require_token` dependency + WS token check.
- [x] **D-4** Overlay PNG endpoints (occupancy + clearance + rooms per floor) — shipped as part of Phase 2b.
- [x] **D-5** Dockerfile (multi-stage) + static mount + SPA fallback; `render.yaml`; `.dockerignore`.
- [~] **D-6** Deployed to Render + R2 + **Neon** Postgres. Hosted but **unstable on the free 512 MB instance** — the 38 MB test IFC OOMs during prep; smaller models work. Standard 2 GB tier fixes this; left as-is for the demo with the caveat documented. See **§11**.

---

## 9. What This Phase Does NOT Include

| Feature | Deferred to |
|---|---|
| Presigned direct-to-R2 upload | Optimization if proxy upload strains |
| Multi-user accounts / real auth | Scale-out |
| Redis/Celery queue, separate worker service | Scale-out (if prep contention appears) |
| Horizontal scaling / multiple instances | Scale-out (single-worker prep assumes one instance) |
| CDN for glb assets | Optimization (can front R2 with Cloudflare later) |

---

## 10. Open Questions

1. ~~**Render instance tier**~~ — confirmed: free 512 MB is **not enough** for the 38 MB test IFC (OOM during mesh tessellation); Standard 2 GB clears it. Left on free for the demo with a documented caveat.
2. ~~**Postgres provider**~~ — picked **Neon** (better free tier compute window). Autosuspend `AdminShutdown` handled by `psycopg_pool.ConnectionPool(check=ConnectionPool.check_connection)` (pings on checkout, recycles dead conns).
3. **R2 lifecycle** — should orphaned models/routes be garbage-collected, or is manual delete enough for single-user? (Open.)
4. **Cold-start latency** — free Render spin-down + Neon autosuspend stack to a ~10-20 s first request; acceptable for single-user demo.

---

## 11. As-deployed (2026-05-29)

- **Hosting:** Render Web Service (free), one multi-stage Docker image.
- **Blobs:** Cloudflare R2 (free tier).
- **Metadata:** Neon Postgres (free tier, autosuspend on).
- **Auth:** `IFCBOX_APP_TOKEN` shared secret; required when set, off when unset (local dev/tests).
- **Known issue:** the 38 MB test IFC OOM-kills the prep worker on the free
  512 MB Render instance. Smaller IFCs (a few MB, residential single-storey)
  prepare successfully. The user guide steers people to local mode for the
  full experience.
