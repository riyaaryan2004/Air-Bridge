import argparse
import socket
import threading
from pathlib import Path

from .protocol import CHUNK_SIZE, recv_exact, recv_json, send_json, unique_path


class ChatClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        room: str,
        download_dir: Path,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.room = room
        self.download_dir = download_dir
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = threading.Event()
        self.running.set()

    def start(self) -> None:
        self.sock.connect((self.host, self.port))
        send_json(
            self.sock,
            {"type": "join", "username": self.username, "room": self.room},
        )
        receiver = threading.Thread(target=self.receive_loop, daemon=True)
        receiver.start()

        print("Commands: /file <path>, /users, /quit")
        try:
            while self.running.is_set():
                text = input()
                if not text.strip():
                    continue
                if text.startswith("/file "):
                    self.send_file(text[6:].strip().strip('"'))
                elif text == "/users":
                    send_json(self.sock, {"type": "users"})
                elif text == "/quit":
                    send_json(self.sock, {"type": "quit"})
                    self.running.clear()
                else:
                    send_json(self.sock, {"type": "chat", "message": text})
        except (KeyboardInterrupt, EOFError):
            self.running.clear()
        finally:
            try:
                self.sock.close()
            except OSError:
                pass

    def receive_loop(self) -> None:
        while self.running.is_set():
            try:
                payload = recv_json(self.sock)
                payload_type = payload.get("type")
                if payload_type == "chat":
                    print(f"[{payload.get('sender')}] {payload.get('message')}")
                elif payload_type == "system":
                    print(f"* {payload.get('message')}")
                elif payload_type == "error":
                    print(f"! {payload.get('message')}")
                elif payload_type == "file":
                    self.receive_file(payload)
                else:
                    print(f"! Unknown server packet: {payload}")
            except Exception as exc:
                if self.running.is_set():
                    print(f"! Disconnected from server: {exc}")
                self.running.clear()
                break

    def send_file(self, path_text: str) -> None:
        path = Path(path_text).expanduser()
        if not path.is_file():
            print(f"! File not found: {path}")
            return

        size = path.stat().st_size
        send_json(
            self.sock,
            {"type": "file", "filename": path.name, "size": size},
        )
        with path.open("rb") as file:
            while True:
                chunk = file.read(CHUNK_SIZE)
                if not chunk:
                    break
                self.sock.sendall(chunk)
        print(f"* Sent file: {path.name} ({size} bytes)")

    def receive_file(self, payload: dict) -> None:
        size = int(payload.get("size", 0))
        filename = str(payload.get("filename", "received_file"))
        sender = payload.get("sender", "unknown")
        output_path = unique_path(self.download_dir, filename)

        remaining = size
        with output_path.open("wb") as file:
            while remaining > 0:
                chunk = recv_exact(self.sock, min(CHUNK_SIZE, remaining))
                file.write(chunk)
                remaining -= len(chunk)

        print(f"* File from {sender}: {output_path} ({size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a ChatShare terminal client")
    parser.add_argument("--host", default="127.0.0.1", help="Server host/IP")
    parser.add_argument("--port", type=int, default=12345, help="Server TCP port")
    parser.add_argument("--username", help="Display name")
    parser.add_argument("--room", help="Room name/id")
    parser.add_argument(
        "--downloads",
        default="downloads",
        help="Folder where received files are saved",
    )
    args = parser.parse_args()

    username = args.username or input("Username: ").strip() or "anonymous"
    room = args.room or input("Room: ").strip() or "general"
    ChatClient(
        host=args.host,
        port=args.port,
        username=username,
        room=room,
        download_dir=Path(args.downloads),
    ).start()


if __name__ == "__main__":
    main()

