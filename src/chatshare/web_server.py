import argparse
import base64
import hashlib
import json
import mimetypes
import socket
import struct
import threading
import urllib.parse
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Set

from .protocol import safe_filename, unique_path
from .db.database import (
    authenticate_user,
    create_room,
    create_session,
    create_user,
    delete_account,
    delete_room,
    get_friend_data,
    get_or_create_direct_room,
    get_room_history,
    get_user_profile,
    get_user_by_token,
    get_user_rooms,
    init_db,
    invite_friend_to_group,
    now_text,
    remove_friendship,
    request_room_join,
    respond_friend_request,
    respond_room_invite,
    respond_room_join_request,
    save_file_message,
    save_message,
    search_users,
    send_friend_request,
    update_group_description,
    update_user_profile_photo,
    user_in_room,
)

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
UPLOAD_DIR = ROOT / "web_uploads"
PROFILE_PHOTO_DIR = UPLOAD_DIR / "profile_photos"
MAX_PROFILE_PHOTO_SIZE = 5 * 1024 * 1024
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
mimetypes.add_type("audio/webm", ".webm")
mimetypes.add_type("audio/ogg", ".ogg")


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    body = handler.rfile.read(length)
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def get_request_token(handler: BaseHTTPRequestHandler, params: Optional[dict] = None) -> Optional[str]:
    if params is None:
        parsed = urllib.parse.urlparse(handler.path)
        params = urllib.parse.parse_qs(parsed.query)
    token = params.get("token", [None])[0]
    if token:
        return token
    return handler.headers.get("X-Auth-Token")


def get_auth_user(handler: BaseHTTPRequestHandler, params: Optional[dict] = None) -> Optional[str]:
    token = get_request_token(handler, params)
    return get_user_by_token(token)


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
                "type": "history",
                "room": client.room,
                "messages": get_room_history(client.room),
            },
        )
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

    def broadcast(self, room: str, payload: dict, exclude: Optional[WebClient] = None) -> None:
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
        elif parsed.path == "/api/me":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            self.send_json(get_user_profile(username))
        elif parsed.path == "/api/users":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            params = urllib.parse.parse_qs(parsed.query)
            query = params.get("search", [""])[0].strip()
            users = search_users(query, username)
            self.send_json({"users": users})
        elif parsed.path == "/api/friends":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            self.send_json(get_friend_data(username))
        elif parsed.path == "/api/rooms":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            self.send_json({"rooms": get_user_rooms(username)})
        elif parsed.path == "/api/history":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            params = urllib.parse.parse_qs(parsed.query)
            room = params.get("room", [""])[0].strip()
            if not room:
                self.send_error(HTTPStatus.BAD_REQUEST, "Room id is required")
                return
            if not user_in_room(username, room):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            self.send_json({"room": room, "messages": get_room_history(room)})
        elif parsed.path.startswith("/files/"):
            self.serve_uploaded_file(parsed.path.removeprefix("/files/"))
        elif parsed.path.startswith("/profile-photos/"):
            self.serve_profile_photo(parsed.path.removeprefix("/profile-photos/"))
        else:
            self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/register":
            body = read_json_body(self)
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", ""))
            if not username or not password:
                self.send_error(HTTPStatus.BAD_REQUEST, "Username and password are required")
                return
            success = create_user(username, password)
            if not success:
                self.send_json({"ok": False, "error": "Username already exists"})
                return
            token = create_session(username)
            self.send_json({"ok": True, "token": token, "username": username})
            return
        if parsed.path == "/api/login":
            body = read_json_body(self)
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", ""))
            if not username or not password or not authenticate_user(username, password):
                self.send_json({"ok": False, "error": "Invalid username or password"})
                return
            token = create_session(username)
            self.send_json({"ok": True, "token": token, "username": username})
            return
        if parsed.path == "/api/friends/request":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            target = str(body.get("target", "")).strip()
            success = send_friend_request(username, target)
            self.send_json({"ok": success})
            return
        if parsed.path == "/api/friends/respond":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            requestor = str(body.get("requestor", "")).strip()
            accept = bool(body.get("accept", False))
            success = respond_friend_request(requestor, username, accept)
            self.send_json({"ok": success})
            return
        if parsed.path == "/api/friends/remove":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            target = str(body.get("target", "")).strip()
            success = remove_friendship(username, target)
            self.send_json({"ok": success})
            return
        if parsed.path == "/api/account/delete":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            delete_account(username)
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/profile/photo":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            content_type = self.headers.get("Content-Type", "")
            size = int(self.headers.get("Content-Length", "0"))
            if not content_type.startswith("image/") or size <= 0:
                self.send_json({"ok": False, "error": "Choose an image file"})
                return
            if size > MAX_PROFILE_PHOTO_SIZE:
                self.send_json({"ok": False, "error": "Profile photo must be 5 MB or smaller"})
                return
            extension = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ".jpg"
            if extension == ".jpe":
                extension = ".jpg"
            filename = safe_filename(f"{username}_profile{extension}")
            output_path = unique_path(PROFILE_PHOTO_DIR, filename)
            remaining = size
            with output_path.open("wb") as file:
                while remaining > 0:
                    chunk = self.rfile.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    file.write(chunk)
                    remaining -= len(chunk)
            photo_url = f"/profile-photos/{urllib.parse.quote(output_path.name)}"
            update_user_profile_photo(username, photo_url)
            self.send_json({"ok": True, "profile_photo": photo_url})
            return
        if parsed.path == "/api/rooms":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            title = str(body.get("title", "")).strip()
            members = body.get("members", [])
            if not isinstance(members, list):
                members = []
            members = [str(member).strip() for member in members]
            if not title:
                self.send_error(HTTPStatus.BAD_REQUEST, "Room title is required")
                return
            room_id = create_room(title, username, True, members)
            self.send_json({"ok": True, "room_id": room_id})
            return
        if parsed.path == "/api/rooms/add-member":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            room_id = str(body.get("room_id", "")).strip()
            target = str(body.get("target", "")).strip()
            if not room_id or not target:
                self.send_json({"ok": False, "error": "Room and friend are required"})
                return
            success, message = invite_friend_to_group(room_id, username, target)
            self.send_json({"ok": success, "message": message, "pending": success, "error": "" if success else message})
            return
        if parsed.path == "/api/rooms/delete":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            room_id = str(body.get("room_id", "")).strip()
            if not room_id:
                self.send_json({"ok": False, "error": "Room is required"})
                return
            success, error = delete_room(room_id, username)
            if success:
                hub.broadcast(
                    room_id,
                    {
                        "type": "room_deleted",
                        "room": room_id,
                        "message": "This group was deleted",
                        "time": now_text(),
                    },
                    exclude=None,
                )
            self.send_json({"ok": success, "error": error})
            return
        if parsed.path == "/api/rooms/description":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            room_id = str(body.get("room_id", "")).strip()
            description = str(body.get("description", ""))
            if not room_id:
                self.send_json({"ok": False, "error": "Room is required"})
                return
            success, error = update_group_description(room_id, username, description)
            if success:
                hub.broadcast(
                    room_id,
                    {
                        "type": "system",
                        "message": "Group description updated",
                        "time": now_text(),
                    },
                    exclude=None,
                )
            self.send_json({"ok": success, "error": error})
            return
        if parsed.path == "/api/rooms/join":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            room_id = str(body.get("room_id", "")).strip()
            if not room_id:
                self.send_json({"ok": False, "error": "Room ID is required"})
                return
            success, message, pending = request_room_join(room_id, username)
            if not success:
                self.send_json({"ok": False, "error": message})
                return
            self.send_json({"ok": True, "room_id": room_id, "pending": pending, "message": message})
            return
        if parsed.path == "/api/rooms/respond-join":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            room_id = str(body.get("room_id", "")).strip()
            requestor = str(body.get("requestor", "")).strip()
            accept = bool(body.get("accept", False))
            success, error = respond_room_join_request(room_id, username, requestor, accept)
            if success and accept:
                hub.broadcast(
                    room_id,
                    {
                        "type": "system",
                        "message": f"{requestor} joined the group",
                        "time": now_text(),
                    },
                    exclude=None,
                )
            self.send_json({"ok": success, "error": error})
            return
        if parsed.path == "/api/rooms/respond-invite":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            room_id = str(body.get("room_id", "")).strip()
            inviter = str(body.get("inviter", "")).strip()
            accept = bool(body.get("accept", False))
            success, error = respond_room_invite(room_id, username, inviter, accept)
            if success and accept:
                hub.broadcast(
                    room_id,
                    {
                        "type": "system",
                        "message": f"{username} joined the group",
                        "time": now_text(),
                    },
                    exclude=None,
                )
            self.send_json({"ok": success, "error": error})
            return
        if parsed.path == "/api/rooms/direct":
            username = get_auth_user(self)
            if not username:
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            body = read_json_body(self)
            target = str(body.get("target", "")).strip()
            if not target:
                self.send_json({"ok": False, "error": "Target username is required"})
                return
            room_id = get_or_create_direct_room(username, target)
            if not room_id:
                self.send_json({"ok": False, "error": "Cannot create direct room"})
                return
            self.send_json({"ok": True, "room_id": room_id})
            return
        if parsed.path != "/upload":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        params = urllib.parse.parse_qs(parsed.query)
        room = params.get("room", [""])[0].strip()
        token = params.get("token", [None])[0]
        username = get_user_by_token(token)
        if not username or not room or not user_in_room(username, room):
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return
        raw_name = urllib.parse.unquote(params.get("filename", ["shared_file"])[0])
        upload_kind = params.get("kind", ["file"])[0]
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
            "kind": "voice" if upload_kind == "voice" else "file",
            "sender": username,
            "filename": output_path.name,
            "size": size,
            "url": f"/files/{urllib.parse.quote(output_path.name)}",
            "time": now_text(),
        }
        payload["id"] = save_file_message(room, payload)
        hub.broadcast(room, payload)
        self.send_json({"ok": True, "file": payload})

    def handle_websocket(self, parsed) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return

        params = urllib.parse.parse_qs(parsed.query)
        token = params.get("token", [None])[0]
        username = get_user_by_token(token)
        if not username:
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return
        room = params.get("room", [""])[0].strip()
        if not room or not user_in_room(username, room):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
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
        if not user_in_room(client.username, client.room):
            self.send(
                client,
                {
                    "type": "room_deleted",
                    "room": client.room,
                    "message": "This conversation is no longer available",
                    "time": now_text(),
                },
            )
            return
        message_type = message.get("type")
        if message_type == "chat":
            text = str(message.get("message", "")).strip()
            if text:
                message_id = save_message(client.room, client.username, text)
                hub.broadcast(
                    client.room,
                    {
                        "type": "chat",
                        "id": message_id,
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
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", content_type)
        disposition = "inline" if content_type.startswith(("audio/", "image/")) else "attachment"
        self.send_header("Content-Disposition", f'{disposition}; filename="{file_path.name}"')
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        with file_path.open("rb") as file:
            while True:
                chunk = file.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def serve_profile_photo(self, filename: str) -> None:
        safe_name = safe_filename(urllib.parse.unquote(filename))
        file_path = (PROFILE_PHOTO_DIR / safe_name).resolve()
        if PROFILE_PHOTO_DIR.resolve() not in file_path.parents and file_path != PROFILE_PHOTO_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.OK)
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", content_type)
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
    PROFILE_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    server = ThreadingHTTPServer((args.host, args.port), ChatWebHandler)
    ip = local_ip() if args.host in ("0.0.0.0", "") else args.host
    print("ChatShare LAN web server running")
    print(f"Local:   http://127.0.0.1:{args.port}")
    print(f"Network: http://{ip}:{args.port}")
    print("Open the Network URL on devices connected to the same Wi-Fi/LAN.")
    server.serve_forever()


if __name__ == "__main__":
    main()

