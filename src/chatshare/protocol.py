import json
import socket
import struct
from pathlib import Path


HEADER_SIZE = 4
CHUNK_SIZE = 64 * 1024


class ProtocolError(Exception):
    """Raised when a socket payload is incomplete or invalid."""


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ProtocolError("connection closed while receiving data")
        data.extend(chunk)
    return bytes(data)


def send_json(sock: socket.socket, payload: dict) -> None:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack("!I", len(encoded)))
    sock.sendall(encoded)


def recv_json(sock: socket.socket) -> dict:
    header = recv_exact(sock, HEADER_SIZE)
    size = struct.unpack("!I", header)[0]
    if size <= 0:
        raise ProtocolError("empty JSON payload")
    try:
        return json.loads(recv_exact(sock, size).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid JSON payload") from exc


def safe_filename(name: str) -> str:
    clean = Path(name).name.strip()
    return clean or "received_file"


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(filename)
    candidate = directory / safe_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

