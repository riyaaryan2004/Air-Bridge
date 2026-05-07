import argparse
import base64
import hashlib
import json
import mimetypes
import socket
import struct
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Set

from .protocol import safe_filename, unique_path


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
UPLOAD_DIR = ROOT / "web_uploads"
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def now_text() -> str:
    return time.strftime("%H:%M")


def read_ws_frame(sock: socket.socket) -> dict:
    header = sock.recv(2)
    if len(header) < 2:
        raise ConnectionError("websocket closed")

    first, second = header
    opcode = first & 0x0F
    masked = second & 0x80
    length = second & 0x7F

    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]

    mask = recv_exact(sock, 4) if masked else b""
    payload = recv_exact(sock, length) if length else b""
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))

    return {"opcode": opcode, "payload": payload}


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("socket closed")
        data.extend(chunk)
    return bytes(data)


def send_ws_text(sock: socket.socket, payload: dict) -> None:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    header = bytearray([0x81])
    size = len(encoded)
    if size < 126:
        header.append(size)
    elif size < 65536:
        header.extend([126])
        header.extend(struct.pack("!H", size))
    else:
        header.extend([127])
        header.extend(struct.pack("!Q", size))
    sock.sendall(header + encoded)


@dataclass(eq=False)
class WebClient:
    sock: socket.socket
    username: str
    room: str
    send_lock: threading.Lock = field(default_factory=threading.Lock)


class Hub:
    def __init__(self):
        self.rooms: Dict[str, Set[WebClient]] = {}
        self.lock = threading.RLock()

    def join(self, client: WebClient) -> None:
        with self.lock:
            self.rooms.setdefault(client.room, set()).add(client)
            users = self.users(client.room)
        self.send(
            client,
            {
                "type": "system",
                "message": f"Connected to {client.room}",
                "time": now_text(),
            },
        )
        self.broadcast(
            client.room,
            {
                "type": "presence",
                "message": f"{client.username} joined",
                "users": users,
                "time": now_text(),
            },
            exclude=None,
        )

    def leave(self, client: WebClient) -> None:
        with self.lock:
            clients = self.rooms.get(client.room)
            if not clients or client not in clients:
                return
            clients.remove(client)
            if not clients:
                self.rooms.pop(client.room, None)
            users = self.users(client.room)
        self.broadcast(
            client.room,
            {
                "type": "presence",
                "message": f"{client.username} left",
                "users": users,
                "time": now_text(),
            },
            exclude=None,
        )

    def users(self, room: str) -> list:
        clients = self.rooms.get(room, set())
        return sorted(client.username for client in clients)

    def broadcast(self, room: str, payload: dict, exclude: WebClient | None = None) -> None:
        with self.lock:
            clients = list(self.rooms.get(room, set()))
        for client in clients:
            if client is exclude:
                continue
            self.send(client, payload)

    def send(self, client: WebClient, payload: dict) -> None:
        try:
            with client.send_lock:
                send_ws_text(client.sock, payload)
        except OSError:
            self.leave(client)


hub = Hub()


class ChatWebHandler(BaseHTTPRequestHandler):
    server_version = "ChatShareWeb/1.0"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/ws":
            self.handle_websocket(parsed)
        elif parsed.path.startswith("/files/"):
            self.serve_uploaded_file(parsed.path.removeprefix("/files/"))
        else:
            self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/upload":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        params = urllib.parse.parse_qs(parsed.query)
        room = params.get("room", ["general"])[0].strip() or "general"
        username = params.get("username", ["anonymous"])[0].strip() or "anonymous"
        raw_name = urllib.parse.unquote(params.get("filename", ["shared_file"])[0])
        filename = safe_filename(raw_name)
        size = int(self.headers.get("Content-Length", "0"))

        output_path = unique_path(UPLOAD_DIR, filename)
        remaining = size
        with output_path.open("wb") as file:
            while remaining > 0:
                chunk = self.rfile.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                file.write(chunk)
                remaining -= len(chunk)

        payload = {
            "type": "file",
            "sender": username,
            "filename": output_path.name,
            "size": size,
            "url": f"/files/{urllib.parse.quote(output_path.name)}",
            "time": now_text(),
        }
        hub.broadcast(room, payload)
        self.send_json({"ok": True, "file": payload})

    def handle_websocket(self, parsed) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return

        params = urllib.parse.parse_qs(parsed.query)
        username = params.get("username", ["anonymous"])[0].strip() or "anonymous"
        room = params.get("room", ["general"])[0].strip() or "general"
        accept = base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode()).digest()).decode()

        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        client = WebClient(self.connection, username, room)
        hub.join(client)
        try:
            while True:
                frame = read_ws_frame(self.connection)
                opcode = frame["opcode"]
                if opcode == 0x8:
                    break
                if opcode != 0x1:
                    continue
                message = json.loads(frame["payload"].decode("utf-8"))
                self.handle_socket_message(client, message)
        except (ConnectionError, OSError, json.JSONDecodeError):
            pass
        finally:
            hub.leave(client)

    def handle_socket_message(self, client: WebClient, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "chat":
            text = str(message.get("message", "")).strip()
            if text:
                hub.broadcast(
                    client.room,
                    {
                        "type": "chat",
                        "sender": client.username,
                        "message": text,
                        "time": now_text(),
                    },
                    exclude=None,
                )
        elif message_type == "typing":
            hub.broadcast(
                client.room,
                {
                    "type": "typing",
                    "sender": client.username,
                    "isTyping": bool(message.get("isTyping")),
                },
                exclude=client,
            )

    def serve_static(self, request_path: str) -> None:
        if request_path in ("", "/"):
            request_path = "/index.html"
        relative = request_path.lstrip("/")
        file_path = (WEB_DIR / relative).resolve()
        if WEB_DIR.resolve() not in file_path.parents and file_path != WEB_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_uploaded_file(self, filename: str) -> None:
        safe_name = safe_filename(urllib.parse.unquote(filename))
        file_path = (UPLOAD_DIR / safe_name).resolve()
        if UPLOAD_DIR.resolve() not in file_path.parents and file_path != UPLOAD_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        with file_path.open("rb") as file:
            while True:
                chunk = file.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def send_json(self, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ChatShare LAN web app")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind")
    parser.add_argument("--port", type=int, default=5000, help="HTTP/WebSocket port")
    args = parser.parse_args()

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), ChatWebHandler)
    ip = local_ip() if args.host in ("0.0.0.0", "") else args.host
    print("ChatShare LAN web server running")
    print(f"Local:   http://127.0.0.1:{args.port}")
    print(f"Network: http://{ip}:{args.port}")
    print("Open the Network URL on devices connected to the same Wi-Fi/LAN.")
    server.serve_forever()


if __name__ == "__main__":
    main()
