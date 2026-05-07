import hashlib
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "chatshare.db"
DB_CONN = None
DB_LOCK = threading.RLock()


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

