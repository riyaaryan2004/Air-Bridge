const joinPanel = document.querySelector("#joinPanel");
const chatPanel = document.querySelector("#chatPanel");
const joinForm = document.querySelector("#joinForm");
const messageForm = document.querySelector("#messageForm");
const usernameInput = document.querySelector("#usernameInput");
const roomInput = document.querySelector("#roomInput");
const messageInput = document.querySelector("#messageInput");
const fileInput = document.querySelector("#fileInput");
const folderInput = document.querySelector("#folderInput");
const messages = document.querySelector("#messages");
const usersList = document.querySelector("#usersList");
const roomTitle = document.querySelector("#roomTitle");
const connectionStatus = document.querySelector("#connectionStatus");
const typingLine = document.querySelector("#typingLine");
const uploadProgress = document.querySelector("#uploadProgress");
const uploadBar = document.querySelector("#uploadBar");

let socket;
let username = "";
let room = "";
let typingTimer;

joinForm.addEventListener("submit", (event) => {
  event.preventDefault();
  username = usernameInput.value.trim();
  room = roomInput.value.trim() || "general";
  if (!username) return;
  connect();
});

messageForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text || !socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "chat", message: text }));
  messageInput.value = "";
  sendTyping(false);
});

messageInput.addEventListener("input", () => {
  sendTyping(true);
  clearTimeout(typingTimer);
  typingTimer = setTimeout(() => sendTyping(false), 900);
});

fileInput.addEventListener("change", () => {
  uploadFiles(fileInput.files);
  fileInput.value = "";
});

folderInput.addEventListener("change", () => {
  uploadFiles(folderInput.files);
  folderInput.value = "";
});

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const url = `${protocol}://${location.host}/ws?username=${encodeURIComponent(username)}&room=${encodeURIComponent(room)}`;
  socket = new WebSocket(url);
  roomTitle.textContent = room;
  joinPanel.classList.add("hidden");
  chatPanel.classList.remove("hidden");
  setStatus("Connecting", false);

  socket.addEventListener("open", () => setStatus("Online", true));
  socket.addEventListener("close", () => setStatus("Offline", false));
  socket.addEventListener("message", (event) => handleMessage(JSON.parse(event.data)));
}

function handleMessage(data) {
  if (data.type === "chat") {
    addMessage({
      sender: data.sender,
      text: data.message,
      time: data.time,
      mine: data.sender === username,
    });
  }

  if (data.type === "system") {
    addSystem(data.message);
  }

  if (data.type === "presence") {
    renderUsers(data.users || []);
    addSystem(data.message);
  }

  if (data.type === "typing") {
    typingLine.textContent = data.isTyping ? `${data.sender} is typing` : "";
  }

  if (data.type === "file") {
    addFileMessage(data);
  }
}

function addMessage({ sender, text, time, mine }) {
  const item = document.createElement("article");
  item.className = `message${mine ? " mine" : ""}`;
  item.innerHTML = `
    <div class="meta"><strong>${escapeHtml(mine ? "You" : sender)}</strong><span>${escapeHtml(time || "")}</span></div>
    <div class="text">${escapeHtml(text)}</div>
  `;
  messages.appendChild(item);
  scrollMessages();
}

function addFileMessage(data) {
  const mine = data.sender === username;
  const item = document.createElement("article");
  item.className = `message${mine ? " mine" : ""}`;
  item.innerHTML = `
    <div class="meta"><strong>${escapeHtml(mine ? "You" : data.sender)}</strong><span>${escapeHtml(data.time || "")}</span></div>
    <div class="text">${escapeHtml(data.filename)} (${formatBytes(data.size || 0)})</div>
    <a class="file-link" href="${data.url}" download>Download</a>
  `;
  messages.appendChild(item);
  scrollMessages();
}

function addSystem(text) {
  const item = document.createElement("article");
  item.className = "message system";
  item.textContent = text;
  messages.appendChild(item);
  scrollMessages();
}

function renderUsers(users) {
  usersList.innerHTML = "";
  users.forEach((name) => {
    const item = document.createElement("div");
    item.className = "user-chip";
    item.innerHTML = `<span class="dot"></span><span>${escapeHtml(name)}</span>`;
    usersList.appendChild(item);
  });
}

async function uploadFiles(files) {
  for (const file of files) {
    await uploadFile(file);
  }
}

function uploadFile(file) {
  return new Promise((resolve) => {
  const xhr = new XMLHttpRequest();
  const displayName = file.webkitRelativePath || file.name;
  const url = `/upload?username=${encodeURIComponent(username)}&room=${encodeURIComponent(room)}&filename=${encodeURIComponent(displayName)}`;
  xhr.open("POST", url);
  uploadProgress.classList.remove("hidden");
  uploadBar.style.width = "0%";

  xhr.upload.addEventListener("progress", (event) => {
    if (!event.lengthComputable) return;
    uploadBar.style.width = `${Math.round((event.loaded / event.total) * 100)}%`;
  });

  xhr.addEventListener("loadend", () => {
    uploadBar.style.width = "100%";
    setTimeout(() => uploadProgress.classList.add("hidden"), 500);
    resolve();
  });

  xhr.send(file);
  });
}

function sendTyping(isTyping) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "typing", isTyping }));
}

function setStatus(text, online) {
  connectionStatus.textContent = text;
  connectionStatus.classList.toggle("online", online);
}

function scrollMessages() {
  messages.scrollTop = messages.scrollHeight;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
