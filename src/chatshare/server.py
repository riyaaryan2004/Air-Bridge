import argparse
import socket
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .protocol import CHUNK_SIZE, ProtocolError, recv_exact, recv_json, send_json


@dataclass
class Client:
    sock: socket.socket
    address: tuple
    username: str
    room: str
    send_lock: threading.Lock = field(default_factory=threading.Lock)


class ChatServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 12345):
        self.host = host
        self.port = port
        self.clients: List[Client] = []
        self.lock = threading.RLock()
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def start(self) -> None:
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen()
        print(f"ChatShare server listening on {self.host}:{self.port}")
        try:
            while True:
                sock, address = self.server_socket.accept()
                thread = threading.Thread(
                    target=self.handle_connection,
                    args=(sock, address),
                    daemon=True,
                )
                thread.start()
        finally:
            self.server_socket.close()

    def handle_connection(self, sock: socket.socket, address: tuple) -> None:
        client: Optional[Client] = None
        try:
            join = recv_json(sock)
            if join.get("type") != "join":
                send_json(sock, {"type": "error", "message": "First packet must be join"})
                return

            username = str(join.get("username", "")).strip() or "anonymous"
            room = str(join.get("room", "")).strip() or "general"
            client = Client(sock=sock, address=address, username=username, room=room)

            with self.lock:
                self.clients.append(client)
                room_count = len(self.room_clients(room))

            self.send_to_client(
                client,
                {
                    "type": "system",
                    "message": f"Connected as {username} in room '{room}'",
                },
            )
            self.broadcast_system(
                room,
                f"{username} joined the room. Users online here: {room_count}",
                exclude=client,
            )
            print(f"{address[0]}:{address[1]} joined room={room} user={username}")

            while True:
                payload = recv_json(sock)
                payload_type = payload.get("type")
                if payload_type == "chat":
                    self.handle_chat(client, payload)
                elif payload_type == "file":
                    self.handle_file(client, payload)
                elif payload_type == "users":
                    self.handle_users(client)
                elif payload_type == "quit":
                    break
                else:
                    self.send_to_client(
                        client,
                        {"type": "error", "message": f"Unknown command: {payload_type}"},
                    )
        except (ConnectionError, OSError, ProtocolError) as exc:
            if client:
                print(f"{client.username} disconnected: {exc}")
            else:
                print(f"{address[0]}:{address[1]} disconnected during handshake: {exc}")
        finally:
            if client:
                self.remove_client(client)
            try:
                sock.close()
            except OSError:
                pass

    def handle_chat(self, client: Client, payload: dict) -> None:
        message = str(payload.get("message", "")).strip()
        if not message:
            return
        self.broadcast(
            client.room,
            {"type": "chat", "sender": client.username, "message": message},
            exclude=client,
        )

    def handle_file(self, client: Client, payload: dict) -> None:
        filename = str(payload.get("filename", "shared_file"))
        size = int(payload.get("size", 0))
        if size < 0:
            raise ProtocolError("invalid file size")

        data = recv_exact(client.sock, size)
        recipients = self.room_clients(client.room, exclude=client)
        header = {
            "type": "file",
            "sender": client.username,
            "filename": filename,
            "size": size,
        }

        for recipient in recipients:
            try:
                with recipient.send_lock:
                    send_json(recipient.sock, header)
                    for offset in range(0, size, CHUNK_SIZE):
                        recipient.sock.sendall(data[offset : offset + CHUNK_SIZE])
            except OSError:
                self.remove_client(recipient)

        self.send_to_client(
            client,
            {
                "type": "system",
                "message": f"File '{filename}' sent to {len(recipients)} user(s)",
            },
        )

    def handle_users(self, client: Client) -> None:
        names = [item.username for item in self.room_clients(client.room)]
        self.send_to_client(
            client,
            {"type": "system", "message": "Users in room: " + ", ".join(names)},
        )

    def broadcast_system(self, room: str, message: str, exclude: Optional[Client] = None) -> None:
        self.broadcast(room, {"type": "system", "message": message}, exclude=exclude)

    def broadcast(self, room: str, payload: dict, exclude: Optional[Client] = None) -> None:
        for client in self.room_clients(room, exclude=exclude):
            self.send_to_client(client, payload)

    def send_to_client(self, client: Client, payload: dict) -> None:
        try:
            with client.send_lock:
                send_json(client.sock, payload)
        except OSError:
            self.remove_client(client)

    def room_clients(self, room: str, exclude: Optional[Client] = None) -> List[Client]:
        with self.lock:
            return [
                client
                for client in self.clients
                if client.room == room and client is not exclude
            ]

    def remove_client(self, client: Client) -> None:
        removed = False
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)
                removed = True
        if removed:
            self.broadcast_system(client.room, f"{client.username} left the room.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ChatShare server")
    parser.add_argument("--host", default="127.0.0.1", help="Host/IP to bind")
    parser.add_argument("--port", type=int, default=12345, help="TCP port to bind")
    args = parser.parse_args()
    ChatServer(args.host, args.port).start()


if __name__ == "__main__":
    main()

