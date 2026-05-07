# Air Bridge

AIR-Bridge is a multi-user messaging and file-sharing system for local networks. It uses Python for the networking/backend logic and keeps the database local on this PC.

## Features

- Multiple users can connect at the same time.
- Users join rooms/groups by ID or invitation.
- Messages are broadcast only inside the sender's room.
- Files can be shared with everyone in the same room.
- Received files are saved in the `downloads/` folder.
- Includes both terminal and Tkinter GUI clients.
- Includes a React frontend that talks to the Python backend.
- Includes the original plain web UI as a fallback.

## Project Structure

```text
Air-Bridge/
  client.py              # terminal client launcher
  client_GUI.py          # GUI client launcher
  server.py              # server launcher
  web_server.py          # Python HTTP/WebSocket/API launcher
  data/                  # local SQLite database
  react_frontend/        # React UI using the Python backend
  src/
    chatshare/
      client.py          # terminal client implementation
      gui.py             # Tkinter GUI client implementation
      protocol.py        # socket framing, JSON headers, file helpers
      server.py          # multi-threaded chat/file server
      web_server.py      # Python HTTP routes, WebSocket chat, file-sharing, SQLite logic
  web/                   # original plain HTML/CSS/JS fallback UI
    index.html
    styles.css
    app.js
  scripts/
    run_client.bat
    run_gui.bat
    run_react.bat
    run_server.bat
    run_web.bat
  downloads/             # received files
  web_uploads/           # files shared through the website
```

## Requirements

Python 3.9 or newer is required for the backend. Node.js is required only for the React frontend.

## React Frontend With Python Backend

The preferred UI is in `react_frontend/`. It keeps the database on this PC and uses the existing Python routes/server.

See `react_frontend/README.md` for setup and run commands.

## Run The Python Backend

Start the web server:

```powershell
python web_server.py
```

The server prints URLs like:

```text
Local:   http://127.0.0.1:5000
Network: http://192.168.1.5:5000
```

Open the `Network` URL from any phone/laptop connected to the same Wi-Fi/LAN.

The Python backend supports:

- login / registration with username and password
- personal and group chat using generated room IDs with saved message history
- friend search, connection requests, and accept/ignore handling
- online users
- typing status
- file upload and download links
- group add/invite requests
- shareable LAN group links that create join requests
- delete account and delete group cleanup in the local database
- local-only sharing without internet

If another device cannot open the URL, allow Python through Windows Firewall and confirm both devices are on the same network.

## Run The React UI

In another terminal:

```powershell
cd react_frontend
npm.cmd install
npm.cmd run dev
```

Open:

```text
http://127.0.0.1:5173
```

The React dev server proxies API, WebSocket, upload, and file requests to the Python backend on port `5000`.

## Run The Python Socket App

Open one terminal for the server:

```powershell
python server.py
```

Open another terminal for each terminal client:

```powershell
python client.py
```

Or run the GUI client:

```powershell
python client_GUI.py
```

You can also pass options:

```powershell
python server.py --host 127.0.0.1 --port 12345
python client.py --username Alice --room lab
python client.py --username Bob --room lab
```

## Terminal Client Commands

```text
/file path/to/file.txt   send a file to the current room
/users                   show users in the current room
/quit                    disconnect
```

Any other text is sent as a normal chat message.

## Network Testing

By default the app runs on `127.0.0.1`, so it is local to your machine. To test across multiple computers on the same network, start the server with your LAN IP and connect clients using `--host <server-ip>`.

For the website version, `python web_server.py` already binds to `0.0.0.0` and prints the LAN URL.
