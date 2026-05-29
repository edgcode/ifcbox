# IFCBox — User Guide

Three ways to use IFCBox: the **hosted web app**, **running the web app locally**, or the **CLI** (engine only). Start with whichever fits.

---

## 1 · Run the web app locally (recommended)

Prereqs: **Python 3.12**, **Node 20**, and an **IFC file** (IFC2X3 or IFC4 with `IfcSpace`s and walls). Auth is **off** locally (leave the token blank).

**Backend** (terminal 1):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m uvicorn api.main:app --port 8000        # IFCBOX_STORAGE defaults to local (FS + SQLite under ./data)
```

**Frontend** (terminal 2):

```bash
cd web
npm install
npm run dev                                        # http://localhost:5173 (proxies /api to :8000)
```

Open `http://localhost:5173`, click **Continue** (blank token), then upload → prepare → open 3D and follow the workflow below.

---

## 2 · The 3D workflow

Once a floor is open in the 3D viewer:

* **Navigate:** left-drag orbit · right-drag pan · scroll zoom.
* **Pick endpoints:** the right panel has a **3D picking** toggle (off by default, so you can navigate without selecting). Turn it **ON**, then:

  * choose **Source** or **Target**, and click a **terminal** (amber sphere), a **room** (cyan sphere, labelled) or any **wall** (drops a free point, shown as a diamond);
  * or pick from the searchable **terminal/room list** in the panel.
* **Right-click any marker** for a context menu (set as source / add as target / remove) — handy when the list is ambiguous.
* **Mode:** **Trunk** (one shared main that branches to all targets) or **Independent** (a separate pipe per target).
* **Systems:** add more **systems** (e.g. one plant room → its zone) with **+ Add**; each routes independently in its own colour.
* **Route all** → pipes render in 3D (junctions sized to the pipe), with length + segment readout and a **Download pipe.glb**.
* **Left panel:**

  * **Wall colour:** Default / Wall thickness / Wall type / Fire rating (read from the IFC), with a legend.
  * **Overlay:** Occupancy / SDF (clearance) / Room types, drawn on a plane at the routing elevation, with a legend.
  * **Clip top:** slice away geometry above a height to look down onto the plan.
  * **Show:** toggle terminals / rooms / room labels.
* **Theme:** Light / Dark toggle in the header.

---

## 3 · Try the hosted app (limited on free tier)

> The hosted deployment may fail or become unresponsive on larger models because the free-tier instance does not have enough RAM for some processing workloads.

1. Open the deployment URL [](https://ifcbox.onrender.com/) and **sign in** with the shared **app token**.
2. **Upload** an IFC model (`.ifc`). It's parsed and listed with its storey count.
3. Click the model → a **Storeys** list. Click **Prepare** on a floor (a residential floor with rooms works best). A progress bar streams `extract → voxelize → shell` over a WebSocket; after ~15-30 s it goes **Ready** with terminal/space counts.
4. Click **Open 3D →**.

Then follow the **3D workflow** above.

> First load after the app has been idle is slow — the free Render instance and the Neon database resume on demand.


---

## 4 · CLI (engine only, no web)

Good for quickly testing the routing engine and generating the debug images.

```bash
source .venv/bin/activate                          # needs requirements-dev.txt (PyVista for the viewer)

# inspect the model
python route.py model.ifc --list-floors
python route.py model.ifc --floor 6 --list-spaces
python route.py model.ifc --floor 6 --list-terminals

# route between two world points, open the PyVista viewer
python route.py model.ifc --floor 6 --start-xyz 5.3,41.8,6.9 --end-xyz 9.3,42.4,6.9

# route between rooms (IfcSpace GlobalIds), export only, write debug PNGs + shell/walls/rooms
python route.py model.ifc --floor 6 --start-room <space_id> --end-room <space_id> --no-view --debug --shell

# batch demo: Flur → adjacent rooms per apartment (Steiner trees)
python demo_routes.py model.ifc --floor 6 --no-view
```

Outputs land in `output/<model-stem>/` — `route.json`, `pipe.glb`, and (with `--debug`) `debug_occupancy.png`, `debug_clearance.png`, `debug_scene.png`. Useful flags: `--clearance-weight`, `--wall-penalty`, `--bend-penalty`, `--corridor-weight`, `--strict-doors`.

---

## 5 · Cloud mode locally (optional)

To exercise the R2 + Postgres backend on your own machine, create a `.env` (gitignored) at the repo root:

```
IFCBOX_STORAGE=cloud
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=ifcbox
DATABASE_URL=postgresql://...:...@<host>.neon.tech/<db>?sslmode=require
IFCBOX_APP_TOKEN=<your-secret>
```

Then run uvicorn as above — it loads `.env`, stores blobs in R2 + metadata in Postgres, and requires the token (`X-App-Token` header, or `?token=` for asset URLs / WebSocket). See [spec-deploy.md](../plans/spec-deploy.md) for the full deployment story.

---

## 6 · Tests

```bash
python -m pytest          # 19 engine + API tests (forced to the local backend; auth off)
```

The tests skip cleanly if the test IFC isn't present.

---

## Notes & troubleshooting

- **Which floor?** Pick a residential/occupied storey with `IfcSpace`s (rooms) — the demo model's floor 6 (`OKFF OG1`) is a good example.
- **Prepare is slow / killed:** preparing a large IFC tessellates a lot of geometry; on a memory-limited host it can run out of RAM. Locally that's fine; hosted, bump the instance size.
- **"Floor not prepared" (409):** prepare the floor first — routing and geometry need the cached `PreparedFloor`.
- **No rooms shaded / "Other":** room types come from `IfcSpace` names (DE + EN patterns); unrecognised names fall to *Other*.
