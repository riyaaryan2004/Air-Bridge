import argparse
import base64
import hashlib
import json
import mimetypes
import secrets
import socket
import sqlite3
import struct
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Set

from .protocol import safe_filename, unique_path


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
UPLOAD_DIR = ROOT / "web_uploads"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "chatshare.db"
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DB_CONN = None
DB_LOCK = threading.RLock()
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


def now_text() -> str:
    return time.strftime("%H:%M")


def db_connect() -> sqlite3.Connection:
    global DB_CONN
    if DB_CONN is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DB_CONN = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        DB_CONN.row_factory = sqlite3.Row
    return DB_CONN


def init_db() -> None:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room TEXT NOT NULL,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                time TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS friends (
                requestor TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (requestor, target)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                title TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_group INTEGER NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS room_members (
                room_id TEXT NOT NULL,
                username TEXT NOT NULL,
                PRIMARY KEY (room_id, username)
            )
            """
        )
        conn.commit()


def hash_password(password: str) -> str:
    salt = "chatshare_salt_2026"
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def create_user(username: str, password: str) -> bool:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, hash_password(password), datetime.utcnow().isoformat()),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def authenticate_user(username: str, password: str) -> bool:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        return bool(row and row["password_hash"] == hash_password(password))


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(24)
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat()
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO sessions (token, username, expires_at) VALUES (?, ?, ?)",
            (token, username, expires_at),
        )
        conn.commit()
    return token


def get_user_by_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, expires_at FROM sessions WHERE token = ?", (token,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
            cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return row["username"]


def get_room_history(room: str, limit: int = 100) -> list[dict]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sender, message, time FROM messages WHERE room = ? ORDER BY id DESC LIMIT ?",
            (room, limit),
        )
        rows = cursor.fetchall()
    return [dict(sender=row["sender"], message=row["message"], time=row["time"]) for row in reversed(rows)]


def save_message(room: str, sender: str, message: str) -> None:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (room, sender, message, time) VALUES (?, ?, ?, ?)",
            (room, sender, message, now_text()),
        )
        conn.commit()


def friendship_accepted(cursor: sqlite3.Cursor, user1: str, user2: str) -> bool:
    cursor.execute(
        "SELECT status FROM friends WHERE ((requestor = ? AND target = ?) OR (requestor = ? AND target = ?)) AND status = ?",
        (user1, user2, user2, user1, "accepted"),
    )
    return cursor.fetchone() is not None


def create_room(title: str, owner: str, is_group: bool = True, members: Optional[list[str]] = None) -> str:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        while True:
            room_id = secrets.token_urlsafe(8)
            cursor.execute("SELECT room_id FROM rooms WHERE room_id = ?", (room_id,))
            if cursor.fetchone() is None:
                break
        cursor.execute(
            "INSERT INTO rooms (room_id, title, created_by, created_at, is_group) VALUES (?, ?, ?, ?, ?)",
            (room_id, title.strip() or None, owner, datetime.utcnow().isoformat(), 1 if is_group else 0),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
            (room_id, owner),
        )
        for member in sorted(set(members or [])):
            member = member.strip()
            if not member or member == owner or not friendship_accepted(cursor, owner, member):
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
                (room_id, member),
            )
        conn.commit()
    return room_id


def add_room_member(room_id: str, username: str) -> bool:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT room_id FROM rooms WHERE room_id = ?", (room_id,))
        if cursor.fetchone() is None:
            return False
        cursor.execute(
            "INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
            (room_id, username),
        )
        conn.commit()
    return True


def add_friend_to_group(room_id: str, actor: str, target: str) -> tuple[bool, str]:
    if actor == target:
        return False, "You are already in this group"
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT is_group FROM rooms WHERE room_id = ?", (room_id,))
        room_row = cursor.fetchone()
        if room_row is None:
            return False, "Room not found"
        if not bool(room_row["is_group"]):
            return False, "Friends can only be added to group rooms"
        cursor.execute(
            "SELECT 1 FROM room_members WHERE room_id = ? AND username = ?",
            (room_id, actor),
        )
        if cursor.fetchone() is None:
            return False, "You are not a member of this room"
        cursor.execute("SELECT username FROM users WHERE username = ?", (target,))
        if cursor.fetchone() is None:
            return False, "User not found"
        if not friendship_accepted(cursor, actor, target):
            return False, "Only accepted friends can be added"
        cursor.execute(
            "INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
            (room_id, target),
        )
        conn.commit()
    return True, ""


def get_user_rooms(username: str) -> list[dict]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT r.room_id, r.title, r.is_group FROM rooms r JOIN room_members m ON r.room_id = m.room_id WHERE m.username = ? ORDER BY r.created_at DESC",
            (username,),
        )
        rows = cursor.fetchall()
        rooms = []
        for row in rows:
            is_group = bool(row["is_group"])
            title = row["title"] or row["room_id"]
            peer = None
            cursor.execute(
                "SELECT username FROM room_members WHERE room_id = ? ORDER BY username",
                (row["room_id"],),
            )
            members = [member_row["username"] for member_row in cursor.fetchall()]
            if not is_group:
                peer = next((member for member in members if member != username), None)
                if peer is None and title.startswith("Chat: "):
                    names = [name.strip() for name in title.removeprefix("Chat: ").split("+")]
                    peer = next((name for name in names if name and name != username), None)
                if peer:
                    title = peer
            rooms.append(
                {
                    "room_id": row["room_id"],
                    "title": title,
                    "is_group": is_group,
                    "peer": peer,
                    "members": members,
                }
            )
    return rooms


def get_or_create_direct_room(user1: str, user2: str) -> Optional[str]:
    if user1 == user2:
        return None
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE username = ?", (user2,))
        if cursor.fetchone() is None:
            return None
        cursor.execute(
            "SELECT status FROM friends WHERE (requestor = ? AND target = ?) OR (requestor = ? AND target = ?)",
            (user1, user2, user2, user1),
        )
        row = cursor.fetchone()
        if row is None or row["status"] != "accepted":
            return None
    users = sorted([user1, user2])
    room_id = hashlib.sha256(f"direct:{users[0]}:{users[1]}".encode("utf-8")).hexdigest()[:16]
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT room_id FROM rooms WHERE room_id = ? AND is_group = 0", (room_id,))
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO rooms (room_id, title, created_by, created_at, is_group) VALUES (?, ?, ?, ?, ?)",
                (room_id, f"Chat: {users[0]} + {users[1]}", user1, datetime.utcnow().isoformat(), 0),
            )
            cursor.execute(
                "INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
                (room_id, users[0]),
            )
            cursor.execute(
                "INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
                (room_id, users[1]),
            )
            conn.commit()
    return room_id





def user_in_room(username: str, room_id: str) -> bool:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM room_members WHERE room_id = ? AND username = ?",
            (room_id, username),
        )
        return cursor.fetchone() is not None


def search_users(query: str, current_user: str) -> list[dict]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        like_query = f"{query}%"
        cursor.execute(
            "SELECT username FROM users WHERE username LIKE ? AND username != ? ORDER BY username LIMIT 20",
            (like_query, current_user),
        )
        matches = [row["username"] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT requestor, target, status FROM friends WHERE requestor = ? OR target = ?",
            (current_user, current_user),
        )
        relations = cursor.fetchall()
    status_map: dict[str, str] = {}
    for row in relations:
        if row["status"] == "accepted":
            friend = row["target"] if row["requestor"] == current_user else row["requestor"]
            status_map[friend] = "friends"
        elif row["status"] == "pending":
            if row["requestor"] == current_user:
                status_map[row["target"]] = "requested"
            else:
                status_map[row["requestor"]] = "incoming"
    return [
        {"username": username, "status": status_map.get(username, "none")}
        for username in matches
    ]


def get_friend_data(username: str) -> dict:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT requestor, target, status FROM friends WHERE requestor = ? OR target = ?",
            (username, username),
        )
        rows = cursor.fetchall()
    friends = []
    incoming = []
    outgoing = []
    for row in rows:
        if row["status"] == "accepted":
            friend = row["target"] if row["requestor"] == username else row["requestor"]
            friends.append(friend)
        elif row["status"] == "pending":
            if row["requestor"] == username:
                outgoing.append(row["target"])
            else:
                incoming.append(row["requestor"])
    return {"friends": sorted(friends), "incoming": sorted(incoming), "outgoing": sorted(outgoing)}


def send_friend_request(requestor: str, target: str) -> bool:
    if requestor == target:
        return False
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE username = ?", (target,))
        if cursor.fetchone() is None:
            return False
        cursor.execute(
            "SELECT status FROM friends WHERE requestor = ? AND target = ?",
            (requestor, target),
        )
        if cursor.fetchone() is not None:
            return False
        cursor.execute(
            "INSERT INTO friends (requestor, target, status, created_at) VALUES (?, ?, ?, ?)",
            (requestor, target, "pending", datetime.utcnow().isoformat()),
        )
        conn.commit()
    return True


def respond_friend_request(requestor: str, target: str, accept: bool) -> bool:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM friends WHERE requestor = ? AND target = ?",
            (requestor, target),
        )
        row = cursor.fetchone()
        if row is None or row["status"] != "pending":
            return False
        if accept:
            cursor.execute(
                "UPDATE friends SET status = ? WHERE requestor = ? AND target = ?",
                ("accepted", requestor, target),
            )
        else:
            cursor.execute("DELETE FROM friends WHERE requestor = ? AND target = ?", (requestor, target))
        conn.commit()
    return True


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
            self.send_json({"username": username})
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
            success, error = add_friend_to_group(room_id, username, target)
            if success:
                hub.broadcast(
                    room_id,
                    {
                        "type": "system",
                        "message": f"{target} was added to the group",
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
            if not room_id or not add_room_member(room_id, username):
                self.send_json({"ok": False, "error": "Room not found"})
                return
            self.send_json({"ok": True, "room_id": room_id})
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
        message_type = message.get("type")
        if message_type == "chat":
            text = str(message.get("message", "")).strip()
            if text:
                save_message(client.room, client.username, text)
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
