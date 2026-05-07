# ChatShare

ChatShare is a multi-user messaging and file-sharing system for local networks. It includes the original Python socket clients plus a browser-based LAN web app.

## Features

- Multiple users can connect at the same time.
- Users join rooms by room ID/name.
- Messages are broadcast only inside the sender's room.
- Files can be shared with everyone in the same room.
- Received files are saved in the `downloads/` folder.
- Includes both terminal and Tkinter GUI clients.
- Includes a website UI for devices on the same Wi-Fi/LAN.

## Project Structure

```text
CN_Project/
  client.py              # terminal client launcher
  client_GUI.py          # GUI client launcher
  server.py              # server launcher
  web_server.py          # LAN website launcher
  src/
    chatshare/
      client.py          # terminal client implementation
      gui.py             # Tkinter GUI client implementation
      protocol.py        # socket framing, JSON headers, file helpers
      server.py          # multi-threaded chat/file server
      web_server.py      # HTTP, WebSocket, and file-sharing server
  web/
    index.html
    styles.css
    app.js
  scripts/
    run_client.bat
    run_gui.bat
    run_server.bat
    run_web.bat
  downloads/             # received files
  web_uploads/           # files shared through the website
```

## Requirements

Python 3.9 or newer. No external packages are required.

## Run The LAN Website

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

The website supports:

- room-based group chat
- online users
- typing status
- file upload and download links
- local-only sharing without internet

If another device cannot open the URL, allow Python through Windows Firewall and confirm both devices are on the same network.

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
