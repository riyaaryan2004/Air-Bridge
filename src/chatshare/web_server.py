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
        cursor.execute("PRAGMA table_info(messages)")
        message_columns = {row["name"] for row in cursor.fetchall()}
        if "message_type" not in message_columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN message_type TEXT NOT NULL DEFAULT 'chat'")
        if "kind" not in message_columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN kind TEXT")
        if "filename" not in message_columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN filename TEXT")
        if "size" not in message_columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN size INTEGER NOT NULL DEFAULT 0")
        if "url" not in message_columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN url TEXT")
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
                description TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_group INTEGER NOT NULL
            )
            """
        )
        cursor.execute("PRAGMA table_info(rooms)")
        room_columns = {row["name"] for row in cursor.fetchall()}
        if "description" not in room_columns:
            cursor.execute("ALTER TABLE rooms ADD COLUMN description TEXT")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS room_members (
                room_id TEXT NOT NULL,
                username TEXT NOT NULL,
                PRIMARY KEY (room_id, username)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS room_join_requests (
                room_id TEXT NOT NULL,
                requestor TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (room_id, requestor)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS room_member_invites (
                room_id TEXT NOT NULL,
                inviter TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (room_id, target)
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
            "SELECT id, sender, message, time, message_type, kind, filename, size, url FROM messages WHERE room = ? ORDER BY id DESC LIMIT ?",
            (room, limit),
        )
        rows = cursor.fetchall()
    history = []
    for row in reversed(rows):
        item = {
            "id": row["id"],
            "type": row["message_type"] or "chat",
            "sender": row["sender"],
            "message": row["message"],
            "time": row["time"],
        }
        if item["type"] == "file":
            item.update(
                {
                    "kind": row["kind"] or "file",
                    "filename": row["filename"] or row["message"],
                    "size": int(row["size"] or 0),
                    "url": row["url"] or "",
                }
            )
        history.append(item)
    return history


def save_message(room: str, sender: str, message: str) -> int:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (room, sender, message, time) VALUES (?, ?, ?, ?)",
            (room, sender, message, now_text()),
        )
        message_id = cursor.lastrowid
        conn.commit()
    return int(message_id)


def save_file_message(room: str, payload: dict) -> int:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO messages (room, sender, message, time, message_type, kind, filename, size, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                room,
                str(payload.get("sender", "")),
                str(payload.get("filename", "shared_file")),
                str(payload.get("time", now_text())),
                "file",
                str(payload.get("kind", "file")),
                str(payload.get("filename", "shared_file")),
                int(payload.get("size", 0) or 0),
                str(payload.get("url", "")),
            ),
        )
        message_id = cursor.lastrowid
        conn.commit()
    return int(message_id)


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
            "INSERT INTO rooms (room_id, title, description, created_by, created_at, is_group) VALUES (?, ?, ?, ?, ?, ?)",
            (room_id, title.strip() or None, "", owner, datetime.utcnow().isoformat(), 1 if is_group else 0),
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


def request_room_join(room_id: str, requestor: str) -> tuple[bool, str, bool]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT is_group FROM rooms WHERE room_id = ?", (room_id,))
        room_row = cursor.fetchone()
        if room_row is None:
            return False, "Room not found", False
        cursor.execute(
            "SELECT 1 FROM room_members WHERE room_id = ? AND username = ?",
            (room_id, requestor),
        )
        if cursor.fetchone() is not None:
            return True, "", False
        if not bool(room_row["is_group"]):
            return False, "Direct chats cannot be joined by ID", False
        cursor.execute(
            "SELECT status FROM room_join_requests WHERE room_id = ? AND requestor = ?",
            (room_id, requestor),
        )
        row = cursor.fetchone()
        if row is not None and row["status"] == "pending":
            return True, "Join request already pending", True
        cursor.execute(
            "INSERT OR REPLACE INTO room_join_requests (room_id, requestor, status, created_at) VALUES (?, ?, ?, ?)",
            (room_id, requestor, "pending", datetime.utcnow().isoformat()),
        )
        conn.commit()
    return True, "Join request sent", True


def respond_room_join_request(room_id: str, actor: str, requestor: str, accept: bool) -> tuple[bool, str]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM room_members WHERE room_id = ? AND username = ?",
            (room_id, actor),
        )
        if cursor.fetchone() is None:
            return False, "You are not a member of this room"
        cursor.execute(
            "SELECT status FROM room_join_requests WHERE room_id = ? AND requestor = ?",
            (room_id, requestor),
        )
        row = cursor.fetchone()
        if row is None or row["status"] != "pending":
            return False, "Join request not found"
        if accept:
            cursor.execute(
                "INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
                (room_id, requestor),
            )
        cursor.execute(
            "DELETE FROM room_join_requests WHERE room_id = ? AND requestor = ?",
            (room_id, requestor),
        )
        conn.commit()
    return True, ""


def invite_friend_to_group(room_id: str, actor: str, target: str) -> tuple[bool, str]:
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
            return False, "Only accepted friends can be invited"
        cursor.execute(
            "SELECT 1 FROM room_members WHERE room_id = ? AND username = ?",
            (room_id, target),
        )
        if cursor.fetchone() is not None:
            return False, "This friend is already a member"
        cursor.execute(
            "SELECT status FROM room_member_invites WHERE room_id = ? AND target = ?",
            (room_id, target),
        )
        row = cursor.fetchone()
        if row is not None and row["status"] == "pending":
            return True, "Invite already pending"
        cursor.execute(
            "INSERT OR REPLACE INTO room_member_invites (room_id, inviter, target, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (room_id, actor, target, "pending", datetime.utcnow().isoformat()),
        )
        conn.commit()
    return True, "Invite sent"


def respond_room_invite(room_id: str, target: str, inviter: str, accept: bool) -> tuple[bool, str]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM room_member_invites WHERE room_id = ? AND target = ? AND inviter = ?",
            (room_id, target, inviter),
        )
        row = cursor.fetchone()
        if row is None or row["status"] != "pending":
            return False, "Invite not found"
        if accept:
            cursor.execute(
                "INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
                (room_id, target),
            )
        cursor.execute(
            "DELETE FROM room_member_invites WHERE room_id = ? AND target = ?",
            (room_id, target),
        )
        conn.commit()
    return True, ""


def update_group_description(room_id: str, actor: str, description: str) -> tuple[bool, str]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT is_group FROM rooms WHERE room_id = ?", (room_id,))
        room_row = cursor.fetchone()
        if room_row is None:
            return False, "Room not found"
        if not bool(room_row["is_group"]):
            return False, "Only groups have descriptions"
        cursor.execute(
            "SELECT 1 FROM room_members WHERE room_id = ? AND username = ?",
            (room_id, actor),
        )
        if cursor.fetchone() is None:
            return False, "You are not a member of this room"
        cursor.execute(
            "UPDATE rooms SET description = ? WHERE room_id = ?",
            (description.strip()[:300], room_id),
        )
        conn.commit()
    return True, ""


def get_user_rooms(username: str) -> list[dict]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT r.room_id, r.title, r.description, r.created_by, r.is_group FROM rooms r JOIN room_members m ON r.room_id = m.room_id WHERE m.username = ? ORDER BY r.created_at DESC",
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
            cursor.execute(
                "SELECT id, sender, message, time, message_type, kind, filename FROM messages WHERE room = ? ORDER BY id DESC LIMIT 1",
                (row["room_id"],),
            )
            last_message = cursor.fetchone()
            last_message_text = ""
            if last_message:
                last_message_text = last_message["message"]
                if last_message["message_type"] == "file":
                    last_message_text = "Voice message" if last_message["kind"] == "voice" else last_message["filename"] or "Shared file"
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
                    "description": row["description"] or "",
                    "created_by": row["created_by"],
                    "is_owner": row["created_by"] == username,
                    "is_group": is_group,
                    "peer": peer,
                    "members": members,
                    "last_message_id": last_message["id"] if last_message else 0,
                    "last_message_sender": last_message["sender"] if last_message else "",
                    "last_message": last_message_text,
                    "last_message_time": last_message["time"] if last_message else "",
                }
            )
    return rooms


def delete_room(room_id: str, actor: str) -> tuple[bool, str]:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute("SELECT created_by, is_group FROM rooms WHERE room_id = ?", (room_id,))
        room_row = cursor.fetchone()
        if room_row is None:
            return False, "Room not found"
        if not bool(room_row["is_group"]):
            return False, "Only groups can be deleted"
        if room_row["created_by"] != actor:
            return False, "Only the group creator can delete this group"
        cursor.execute("DELETE FROM messages WHERE room = ?", (room_id,))
        cursor.execute("DELETE FROM room_members WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM room_join_requests WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM room_member_invites WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM rooms WHERE room_id = ?", (room_id,))
        conn.commit()
    return True, ""


def delete_account(username: str) -> None:
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT room_id FROM room_members WHERE username = ?",
            (username,),
        )
        affected_rooms = [row["room_id"] for row in cursor.fetchall()]
        cursor.execute("DELETE FROM sessions WHERE username = ?", (username,))
        cursor.execute(
            "DELETE FROM friends WHERE requestor = ? OR target = ?",
            (username, username),
        )
        cursor.execute(
            "DELETE FROM room_join_requests WHERE requestor = ?",
            (username,),
        )
        cursor.execute(
            "DELETE FROM room_member_invites WHERE inviter = ? OR target = ?",
            (username, username),
        )
        cursor.execute("DELETE FROM messages WHERE sender = ?", (username,))
        cursor.execute("DELETE FROM room_members WHERE username = ?", (username,))
        cursor.execute("DELETE FROM users WHERE username = ?", (username,))
        for room_id in affected_rooms:
            cursor.execute(
                "SELECT is_group, created_by FROM rooms WHERE room_id = ?",
                (room_id,),
            )
            room_row = cursor.fetchone()
            if room_row is None:
                continue
            cursor.execute(
                "SELECT username FROM room_members WHERE room_id = ? ORDER BY username",
                (room_id,),
            )
            remaining_members = [row["username"] for row in cursor.fetchall()]
            should_delete = not remaining_members or not bool(room_row["is_group"])
            if should_delete:
                cursor.execute("DELETE FROM messages WHERE room = ?", (room_id,))
                cursor.execute("DELETE FROM room_members WHERE room_id = ?", (room_id,))
                cursor.execute("DELETE FROM room_join_requests WHERE room_id = ?", (room_id,))
                cursor.execute("DELETE FROM room_member_invites WHERE room_id = ?", (room_id,))
                cursor.execute("DELETE FROM rooms WHERE room_id = ?", (room_id,))
            elif room_row["created_by"] == username:
                cursor.execute(
                    "UPDATE rooms SET created_by = ? WHERE room_id = ?",
                    (remaining_members[0], room_id),
                )
        conn.commit()


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
                "INSERT INTO rooms (room_id, title, description, created_by, created_at, is_group) VALUES (?, ?, ?, ?, ?, ?)",
                (room_id, f"Chat: {users[0]} + {users[1]}", "", user1, datetime.utcnow().isoformat(), 0),
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
        cursor.execute(
            """
            SELECT j.room_id, j.requestor, r.title
            FROM room_join_requests j
            JOIN rooms r ON r.room_id = j.room_id
            JOIN room_members m ON m.room_id = j.room_id
            WHERE m.username = ? AND j.status = ? AND j.requestor != ?
            ORDER BY j.created_at DESC
            """,
            (username, "pending", username),
        )
        incoming_join = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT j.room_id, j.requestor, r.title
            FROM room_join_requests j
            JOIN rooms r ON r.room_id = j.room_id
            WHERE j.requestor = ? AND j.status = ?
            ORDER BY j.created_at DESC
            """,
            (username, "pending"),
        )
        outgoing_join = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT i.room_id, i.inviter, i.target, r.title
            FROM room_member_invites i
            JOIN rooms r ON r.room_id = i.room_id
            WHERE i.target = ? AND i.status = ?
            ORDER BY i.created_at DESC
            """,
            (username, "pending"),
        )
        incoming_invite = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT i.room_id, i.inviter, i.target, r.title
            FROM room_member_invites i
            JOIN rooms r ON r.room_id = i.room_id
            WHERE i.inviter = ? AND i.status = ?
            ORDER BY i.created_at DESC
            """,
            (username, "pending"),
        )
        outgoing_invite = [dict(row) for row in cursor.fetchall()]
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
    return {
        "friends": sorted(friends),
        "incoming": sorted(incoming),
        "outgoing": sorted(outgoing),
        "incoming_join": incoming_join,
        "outgoing_join": outgoing_join,
        "incoming_invite": incoming_invite,
        "outgoing_invite": outgoing_invite,
    }


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


def remove_friendship(actor: str, target: str) -> bool:
    if actor == target or not target:
        return False
    conn = db_connect()
    with DB_LOCK:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM friends
            WHERE (requestor = ? AND target = ?)
               OR (requestor = ? AND target = ?)
            """,
            (actor, target, target, actor),
        )
        removed = cursor.rowcount > 0
        users = sorted([actor, target])
        direct_room_id = hashlib.sha256(f"direct:{users[0]}:{users[1]}".encode("utf-8")).hexdigest()[:16]
        cursor.execute(
            "SELECT room_id FROM rooms WHERE room_id = ? AND is_group = 0",
            (direct_room_id,),
        )
        if cursor.fetchone() is not None:
            cursor.execute("DELETE FROM messages WHERE room = ?", (direct_room_id,))
            cursor.execute("DELETE FROM room_members WHERE room_id = ?", (direct_room_id,))
            cursor.execute("DELETE FROM rooms WHERE room_id = ?", (direct_room_id,))
        conn.commit()
    return removed


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
