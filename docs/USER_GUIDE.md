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
* **Route apartments (N)** → one-click demo: auto-discover each apartment on the floor (BFS from each *Flur* through doors, stopped at fire-rated walls) and create one trunk system per apartment, each in its own colour, then routes the lot. The small **↻** beside it re-discovers (use after engine updates) without re-prepping the floor.
* **Left panel:**

  * **Wall colour:** Default / Wall thickness / Wall type / Fire rating (read from the IFC), with a legend.
  * **Overlay:** Occupancy / SDF (clearance) / Room types, drawn on a plane at the routing elevation, with a legend.
  * **Clip top:** slice away geometry above a height to look down onto the plan.
  * **Show:** toggle terminals / rooms / room labels.
* **Theme:** Light / Dark toggle in the header.

---

## 3 · Try the hosted app (slow / unstable on free tier)

> ⚠️ **Free-tier caveats.** The hosted app runs on **Render free (512 MB)** + **Neon free Postgres** + **Cloudflare R2**. Two consequences:
>
> 1. **Large IFCs OOM during prep.** The 38 MB demo model OOM-kills the prep worker on 512 MB. Try a **small residential IFC** (a few MB, single occupied storey) or run locally (§1).
> 2. **First request after idle is slow.** Both Render and Neon spin from cold — expect ~10–30 s for the very first response and the first prepare. The prominent loaders in the UI tell you what stage you're in. Don't refresh.

1. Open [https://ifcbox.onrender.com/](https://ifcbox.onrender.com/) and **sign in** with the shared **app token**.
2. **Upload** an IFC model (`.ifc`). The upload card shows real byte progress, then an indeterminate "Parsing on server" phase while ifcopenshell opens it.
3. Click the model → a **Storeys** list. Click **Prepare** on a residential storey. A progress bar streams `extract → voxelize → shell → apartments` over a WebSocket.
4. Click **Open 3D →**, then follow the **3D workflow** above. Try **Route apartments (N)** for the auto-routing demo.


---

## 4 · CLI (engine only, no web)

Good for quickly testing the routing engine and generating the debug images.

```bash
source .venv/bin/activate                          # needs requirements-dev.txt (PyVista for the viewer)

# inspect the model
python route.py model.ifc --list-floors
python route.py model.ifc --floor 2 --list-spaces
python route.py model.ifc --floor 2 --list-terminals

# route between two world points, open the PyVista viewer
python route.py model.ifc --floor 2 --start-xyz 5.3,41.8,6.9 --end-xyz 9.3,42.4,6.9

# route between rooms (IfcSpace GlobalIds), export only, write debug PNGs + shell/walls/rooms
python route.py model.ifc --floor 2 --start-room <space_id> --end-room <space_id> --no-view --debug --shell

# batch demo: Flur → adjacent rooms per apartment (Steiner trees)
python demo_routes.py model.ifc --floor 2 --no-view
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

- **Which floor?** Pick a residential/occupied storey with `IfcSpace`s (rooms) — the demo model's floor 2 (`OKFF OG1`) is a good example. (Raw-deck levels named `OKRD` / `UKRD` — top / bottom of structural slab in German naming — are filtered out of the storeys list automatically.)
- **Prepare is slow / killed:** preparing a large IFC tessellates a lot of geometry; on a memory-limited host it can run out of RAM. Locally that's fine; hosted, the free Render 512 MB tier won't hold the 38 MB demo IFC — try a smaller model or upgrade the instance.
- **"Route apartments" button missing:** appears only on prepared floors that have at least one named hallway (matching `Flur` / `Korridor` / `Diele` etc.). For floors prepared before this feature shipped, the GET endpoint backfills `apartments.json` on first hit; you can also click the **↻** button to force a re-discovery.
- **"Floor not prepared" (409):** prepare the floor first — routing and geometry need the cached `PreparedFloor`.
- **No rooms shaded / "Other":** room types come from `IfcSpace` names (DE + EN patterns); unrecognised names fall to *Other*.
