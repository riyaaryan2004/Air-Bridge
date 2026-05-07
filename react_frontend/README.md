# AIR-Bridge React Frontend With Python Backend

This is the architecture you asked for:

- React frontend
- Python server and Python routes
- Local SQLite database on this PC
- Existing Python WebSocket chat logic

No Express, no MongoDB, no MERN backend.

## Run

Start the existing Python backend from the repo root:

```powershell
python web_server.py
```

Then start React:

```powershell
cd react_frontend
npm.cmd install
npm.cmd run dev
```

Open:

```text
http://127.0.0.1:5173
```

The Vite dev server proxies `/api`, `/upload`, `/files`, and `/ws` to the Python server at `http://127.0.0.1:5000`.

## Group Links

Open a group, go to group info, and use `Copy Group Link`.

Anyone on the same LAN can open that link, log in, and send a join request. A current group member accepts it from Profile > Requests.

## Build

```powershell
cd react_frontend
npm.cmd run build
```
