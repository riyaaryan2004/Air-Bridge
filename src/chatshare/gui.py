import argparse
import queue
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .protocol import CHUNK_SIZE, recv_exact, recv_json, send_json, unique_path


class ChatGui:
    def __init__(self, host: str, port: int, downloads: Path):
        self.host = host
        self.port = port
        self.downloads = downloads
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.events = queue.Queue()
        self.running = False

        self.root = tk.Tk()
        self.root.title("ChatShare")
        self.root.geometry("720x520")
        self.root.minsize(620, 440)
        self.build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.messages = tk.Text(frame, state="disabled", wrap="word", height=18)
        self.messages.grid(row=0, column=0, columnspan=3, sticky="nsew")

        scrollbar = ttk.Scrollbar(frame, command=self.messages.yview)
        scrollbar.grid(row=0, column=3, sticky="ns")
        self.messages.configure(yscrollcommand=scrollbar.set)

        self.entry = ttk.Entry(frame)
        self.entry.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.entry.bind("<Return>", lambda _event: self.send_message())

        ttk.Button(frame, text="Send", command=self.send_message).grid(
            row=1, column=1, padx=(8, 0), pady=(10, 0)
        )
        ttk.Button(frame, text="File", command=self.send_file).grid(
            row=1, column=2, padx=(8, 0), pady=(10, 0)
        )

    def connect(self) -> None:
        username = simpledialog.askstring("Login", "Username:", parent=self.root)
        if not username:
            self.root.destroy()
            return
        room = simpledialog.askstring("Room", "Room ID:", parent=self.root) or "general"

        try:
            self.sock.connect((self.host, self.port))
            send_json(self.sock, {"type": "join", "username": username, "room": room})
        except OSError as exc:
            messagebox.showerror("Connection failed", str(exc), parent=self.root)
            self.root.destroy()
            return

        self.root.title(f"ChatShare - {username} / {room}")
        self.running = True
        threading.Thread(target=self.receive_loop, daemon=True).start()
        self.root.after(100, self.process_events)

    def run(self) -> None:
        self.root.after(50, self.connect)
        self.root.mainloop()

    def send_message(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        try:
            send_json(self.sock, {"type": "chat", "message": text})
            self.append(f"You: {text}")
        except OSError as exc:
            self.append(f"Send failed: {exc}")

    def send_file(self) -> None:
        path_text = filedialog.askopenfilename(parent=self.root)
        if not path_text:
            return
        path = Path(path_text)
        try:
            size = path.stat().st_size
            send_json(self.sock, {"type": "file", "filename": path.name, "size": size})
            with path.open("rb") as file:
                while True:
                    chunk = file.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self.sock.sendall(chunk)
            self.append(f"You sent file: {path.name} ({size} bytes)")
        except OSError as exc:
            self.append(f"File send failed: {exc}")

    def receive_loop(self) -> None:
        while self.running:
            try:
                payload = recv_json(self.sock)
                payload_type = payload.get("type")
                if payload_type == "file":
                    saved_path = self.receive_file(payload)
                    self.events.put(("text", f"{payload.get('sender')} sent file: {saved_path}"))
                elif payload_type == "chat":
                    self.events.put(
                        ("text", f"{payload.get('sender')}: {payload.get('message')}")
                    )
                elif payload_type == "system":
                    self.events.put(("text", f"* {payload.get('message')}"))
                elif payload_type == "error":
                    self.events.put(("text", f"! {payload.get('message')}"))
            except Exception as exc:
                if self.running:
                    self.events.put(("text", f"! Disconnected: {exc}"))
                break

    def receive_file(self, payload: dict) -> Path:
        size = int(payload.get("size", 0))
        output_path = unique_path(self.downloads, str(payload.get("filename", "file")))
        remaining = size
        with output_path.open("wb") as file:
            while remaining > 0:
                chunk = recv_exact(self.sock, min(CHUNK_SIZE, remaining))
                file.write(chunk)
                remaining -= len(chunk)
        return output_path

    def process_events(self) -> None:
        while True:
            try:
                event_type, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event_type == "text":
                self.append(value)
        if self.running:
            self.root.after(100, self.process_events)

    def append(self, text: str) -> None:
        self.messages.configure(state="normal")
        self.messages.insert(tk.END, text + "\n")
        self.messages.configure(state="disabled")
        self.messages.see(tk.END)

    def close(self) -> None:
        self.running = False
        try:
            send_json(self.sock, {"type": "quit"})
            self.sock.close()
        except OSError:
            pass
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ChatShare GUI client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12345)
    parser.add_argument("--downloads", default="downloads")
    args = parser.parse_args()
    ChatGui(args.host, args.port, Path(args.downloads)).run()


if __name__ == "__main__":
    main()

