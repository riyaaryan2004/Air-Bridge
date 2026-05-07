const joinPanel = document.querySelector("#joinPanel");
const chatPanel = document.querySelector("#chatPanel");
const joinForm = document.querySelector("#joinForm");
const messageForm = document.querySelector("#messageForm");
const usernameInput = document.querySelector("#usernameInput");
const passwordInput = document.querySelector("#passwordInput");
const messageInput = document.querySelector("#messageInput");
const fileInput = document.querySelector("#fileInput");
const folderInput = document.querySelector("#folderInput");
const voiceButton = document.querySelector("#voiceButton");
const messages = document.querySelector("#messages");
const usersList = document.querySelector("#usersList");
const roomsList = document.querySelector("#roomsList");
const newRoomTitleInput = document.querySelector("#newRoomTitleInput");
const groupFriendPicker = document.querySelector("#groupFriendPicker");
const createRoomButton = document.querySelector("#createRoomButton");
const roomIdInput = document.querySelector("#roomIdInput");
const joinRoomButton = document.querySelector("#joinRoomButton");
const friendsList = document.querySelector("#friendsList");
const requestsList = document.querySelector("#requestsList");
const searchInput = document.querySelector("#searchInput");
const searchButton = document.querySelector("#searchButton");
const searchResults = document.querySelector("#searchResults");
const roomTitle = document.querySelector("#roomTitle");
const connectionStatus = document.querySelector("#connectionStatus");
const typingLine = document.querySelector("#typingLine");
const uploadProgress = document.querySelector("#uploadProgress");
const uploadBar = document.querySelector("#uploadBar");
const joinNotice = document.querySelector("#joinNotice");
const joinButton = document.querySelector("#joinButton");
const toggleRegister = document.querySelector("#toggleRegister");
const profileAvatar = document.querySelector("#profileAvatar");
const profileName = document.querySelector("#profileName");
const profileStatus = document.querySelector("#profileStatus");
const roomAvatar = document.querySelector("#roomAvatar");
const logoutButton = document.querySelector("#logoutButton");
const onlineCount = document.querySelector("#onlineCount");
const friendsCount = document.querySelector("#friendsCount");
const voiceFallbackInput = document.createElement("input");
voiceFallbackInput.type = "file";
voiceFallbackInput.accept = "audio/*";
voiceFallbackInput.capture = "microphone";
voiceFallbackInput.hidden = true;
document.body.appendChild(voiceFallbackInput);

let socket;
let username = "";
let room = "";
let token = "";
let isRegisterMode = false;
let typingTimer;
let searchTimer;
let mediaRecorder;
let voiceChunks = [];
let isRecordingVoice = false;
let cachedFriends = [];
let cachedRooms = [];
let currentRoomMeta = null;

joinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  username = usernameInput.value.trim();
  const password = passwordInput.value;
  if (!username || !password) return;

  const result = await authenticate(username, password, isRegisterMode);
  if (!result.ok) {
    joinNotice.textContent = result.error || "Login failed.";
    return;
  }

  token = result.token;
  localStorage.setItem("chatshareToken", token);
  localStorage.setItem("chatshareUsername", username);
  localStorage.removeItem("chatshareRoom");
  room = "";

  updateProfile();
  updateRoomHeader("Select a conversation");
  joinPanel.classList.add("hidden");
  chatPanel.classList.remove("hidden");
  setStatus("Offline", false);
  messages.innerHTML = "";
  addSystem("Welcome! Search for friends, send requests, or create a group chat.");
  await refreshFriendData();
  await refreshRooms();
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

voiceButton.addEventListener("click", () => {
  if (isRecordingVoice) {
    stopVoiceRecording();
  } else {
    startVoiceRecording();
  }
});

voiceFallbackInput.addEventListener("change", () => {
  const [file] = voiceFallbackInput.files;
  if (file) {
    uploadFile(file, { filename: file.name || `voice-${Date.now()}.webm`, kind: "voice" });
  }
  voiceFallbackInput.value = "";
});

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();
  if (!query) {
    searchResults.innerHTML = "";
    return;
  }
  searchTimer = setTimeout(() => searchUsers(query), 250);
});

searchButton.addEventListener("click", () => {
  const query = searchInput.value.trim();
  if (!query) {
    searchResults.innerHTML = "";
    searchInput.focus();
    return;
  }
  searchUsers(query);
});

createRoomButton.addEventListener("click", async () => {
  const title = newRoomTitleInput.value.trim();
  if (!title || !token) return;
  const members = Array.from(groupFriendPicker.querySelectorAll("input:checked")).map((input) => input.value);
  const response = await fetch("/api/rooms", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ title, members }),
  });
  const data = await response.json();
  if (data.ok) {
    newRoomTitleInput.value = "";
    groupFriendPicker.querySelectorAll("input:checked").forEach((input) => {
      input.checked = false;
    });
    await refreshRooms(data.room_id);
  } else {
    addSystem(data.error || "Could not create group.");
  }
});

joinRoomButton.addEventListener("click", async () => {
  const roomId = roomIdInput.value.trim();
  if (!roomId || !token) return;
  const response = await fetch("/api/rooms/join", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ room_id: roomId }),
  });
  const data = await response.json();
  if (data.ok) {
    roomIdInput.value = "";
    await refreshRooms(data.room_id);
  }
});

toggleRegister.addEventListener("click", () => {
  isRegisterMode = !isRegisterMode;
  joinButton.textContent = isRegisterMode ? "Register" : "Login";
  toggleRegister.textContent = isRegisterMode ? "Already have an account? Login" : "Register New Account";
  joinNotice.textContent = isRegisterMode
    ? "Create an account and then join a room after login."
    : "Use your account credentials to login.";
});

logoutButton.addEventListener("click", () => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  token = "";
  username = "";
  room = "";
  localStorage.removeItem("chatshareToken");
  localStorage.removeItem("chatshareUsername");
  localStorage.removeItem("chatshareRoom");
  passwordInput.value = "";
  messageInput.value = "";
  messages.innerHTML = "";
  usersList.innerHTML = "";
  roomsList.innerHTML = "";
  friendsList.innerHTML = "";
  groupFriendPicker.innerHTML = "";
  requestsList.innerHTML = "";
  searchResults.innerHTML = "";
  onlineCount.textContent = "0";
  friendsCount.textContent = "0";
  cachedFriends = [];
  cachedRooms = [];
  currentRoomMeta = null;
  updateProfile();
  updateRoomHeader("Select a conversation");
  setStatus("Offline", false);
  chatPanel.classList.add("hidden");
  joinPanel.classList.remove("hidden");
});

window.addEventListener("load", async () => {
  const savedToken = localStorage.getItem("chatshareToken");
  const savedUsername = localStorage.getItem("chatshareUsername");
  if (savedToken && savedUsername) {
    token = savedToken;
    username = savedUsername;
    usernameInput.value = username;
    updateProfile();
    joinNotice.textContent = "Enter your password and login.";
    joinPanel.classList.remove("hidden");
    chatPanel.classList.add("hidden");
  } else {
    updateProfile();
  }
});

async function authenticate(usernameValue, passwordValue, register) {
  const url = register ? "/api/register" : "/api/login";
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: usernameValue, password: passwordValue }),
    });
    return await response.json();
  } catch (error) {
    return { ok: false, error: "Server unreachable" };
  }
}

async function refreshRooms(selectedRoomId) {
  if (!token) return [];
  try {
    const response = await fetch(`/api/rooms?token=${encodeURIComponent(token)}`);
    const data = await response.json();
    const rooms = data.rooms || [];
    cachedRooms = rooms;
    renderRooms(rooms);
    const activeRoom = rooms.find((item) => item.room_id === room);
    if (activeRoom) {
      currentRoomMeta = activeRoom;
      updateRoomHeader(getRoomDisplayTitle(activeRoom));
      renderFriends(cachedFriends);
    }
    if (!room || selectedRoomId) {
      const nextRoom = rooms.find((item) => item.room_id === selectedRoomId) || rooms[0];
      if (nextRoom) {
        selectRoom(nextRoom);
      }
    }
    return rooms;
  } catch (error) {
    console.warn("Unable to load rooms", error);
    return [];
  }
}

function renderRooms(rooms) {
  roomsList.innerHTML = "";
  if (!rooms.length) {
    roomsList.appendChild(createEmptyState("No conversations yet. Add friends or create a group."));
    return;
  }
  rooms.forEach((item) => {
    const current = item.room_id === room;
    const displayTitle = getRoomDisplayTitle(item);
    const entry = document.createElement("div");
    entry.className = `user-chip room-chip${current ? " active" : ""}`;
    entry.dataset.room = item.room_id;
    entry.innerHTML = `
      <span class="avatar">${getInitials(displayTitle)}</span>
      <span class="room-name" style="flex: 1;">${escapeHtml(displayTitle)}</span>
      <span class="room-kind">${item.is_group ? "Group" : "Chat"}</span>
    `;
    roomsList.appendChild(entry);
  });
}

function selectRoom(roomObj) {
  if (!roomObj) return;
  currentRoomMeta = roomObj;
  if (roomObj.room_id === room) {
    updateRoomHeader(getRoomDisplayTitle(roomObj));
    renderRooms(cachedRooms);
    renderFriends(cachedFriends);
    return;
  }
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  room = roomObj.room_id;
  updateRoomHeader(getRoomDisplayTitle(roomObj));
  renderRooms(cachedRooms);
  renderFriends(cachedFriends);
  messages.innerHTML = "";
  usersList.innerHTML = "";
  onlineCount.textContent = "0";
  setStatus("Connecting", false);
  loadRoomHistory();
  connect();
}

function connect() {
  if (!token || !room) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const url = `${protocol}://${location.host}/ws?token=${encodeURIComponent(token)}&room=${encodeURIComponent(room)}`;
  socket = new WebSocket(url);

  socket.addEventListener("open", () => setStatus("Online", true));
  socket.addEventListener("close", () => setStatus("Offline", false));
  socket.addEventListener("message", (event) => handleMessage(JSON.parse(event.data)));
  socket.addEventListener("error", () => setStatus("Offline", false));
}

async function loadRoomHistory() {
  if (!token || !room) return;
  try {
    const response = await fetch(`/api/history?room=${encodeURIComponent(room)}&token=${encodeURIComponent(token)}`);
    const data = await response.json();
    if (data && Array.isArray(data.messages)) {
      messages.innerHTML = "";
      data.messages.forEach((item) => {
        addMessage({ sender: item.sender, text: item.message, time: item.time, mine: item.sender === username });
      });
      if (data.messages.length) {
        addSystem(`Loaded ${data.messages.length} saved messages.`);
      }
    }
  } catch (error) {
    console.warn("Unable to load room history", error);
  }
}

async function refreshFriendData() {
  if (!token) return;
  try {
    const response = await fetch(`/api/friends?token=${encodeURIComponent(token)}`);
    const data = await response.json();
    if (data) {
      cachedFriends = data.friends || [];
      renderFriends(cachedFriends);
      renderGroupFriendPicker(cachedFriends);
      renderRequests(data.incoming || [], data.outgoing || []);
    }
  } catch (error) {
    console.warn("Unable to refresh friends", error);
  }
}

async function searchUsers(query) {
  if (!token) return;
  try {
    const response = await fetch(`/api/users?search=${encodeURIComponent(query)}&token=${encodeURIComponent(token)}`);
    const data = await response.json();
    renderSearchResults(data.users || []);
  } catch (error) {
    console.warn("Unable to search users", error);
  }
}

function handleMessage(data) {
  if (data.type === "chat") {
    addMessage({ sender: data.sender, text: data.message, time: data.time, mine: data.sender === username });
  }

  if (data.type === "system") {
    addSystem(data.message);
  }

  if (data.type === "presence") {
    renderUsers(data.users || []);
    addSystem(data.message);
  }

  if (data.type === "typing") {
    typingLine.textContent = data.isTyping ? `${data.sender} is typing...` : "";
  }

  if (data.type === "file") {
    addFileMessage(data);
  }

  if (data.type === "history" && Array.isArray(data.messages)) {
    messages.innerHTML = "";
    data.messages.forEach((item) => {
      addMessage({ sender: item.sender, text: item.message, time: item.time, mine: item.sender === username });
    });
    if (data.messages.length) {
      addSystem(`Loaded ${data.messages.length} saved messages.`);
    }
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
  if (data.kind === "voice") {
    item.innerHTML = `
      <div class="meta"><strong>${escapeHtml(mine ? "You" : data.sender)}</strong><span>${escapeHtml(data.time || "")}</span></div>
      <div class="voice-note">
        <button type="button" class="voice-play" aria-label="Play voice message">
          <span class="play-icon" aria-hidden="true"></span>
        </button>
        <div class="voice-wave" aria-hidden="true">
          <span></span><span></span><span></span><span></span><span></span><span></span>
          <span></span><span></span><span></span><span></span><span></span><span></span>
        </div>
        <span class="voice-duration">Voice</span>
        <audio preload="metadata" src="${escapeAttribute(data.url)}"></audio>
      </div>
    `;
    wireVoicePlayer(item.querySelector(".voice-note"));
    messages.appendChild(item);
    scrollMessages();
    return;
  }
  if (isImageFile(data.filename)) {
    item.innerHTML = `
      <div class="meta"><strong>${escapeHtml(mine ? "You" : data.sender)}</strong><span>${escapeHtml(data.time || "")}</span></div>
      <a class="image-message" href="${escapeAttribute(data.url)}" target="_blank" rel="noreferrer">
        <img src="${escapeAttribute(data.url)}" alt="${escapeAttribute(data.filename)}" loading="lazy" />
      </a>
      <div class="file-caption">${escapeHtml(data.filename)} (${formatBytes(data.size || 0)})</div>
    `;
    messages.appendChild(item);
    scrollMessages();
    return;
  }
  item.innerHTML = `
    <div class="meta"><strong>${escapeHtml(mine ? "You" : data.sender)}</strong><span>${escapeHtml(data.time || "")}</span></div>
    <a class="file-link" href="${escapeAttribute(data.url)}" download>
      <span class="file-icon" aria-hidden="true"></span>
      <span>${escapeHtml(data.filename)}</span>
      <small>${formatBytes(data.size || 0)}</small>
    </a>
  `;
  messages.appendChild(item);
  scrollMessages();
}

function wireVoicePlayer(container) {
  if (!container) return;
  const audio = container.querySelector("audio");
  const button = container.querySelector(".voice-play");
  const duration = container.querySelector(".voice-duration");
  if (!audio || !button) return;

  audio.addEventListener("loadedmetadata", () => {
    if (Number.isFinite(audio.duration)) {
      duration.textContent = formatDuration(audio.duration);
    }
  });
  audio.addEventListener("play", () => {
    document.querySelectorAll(".voice-note audio").forEach((otherAudio) => {
      if (otherAudio !== audio) otherAudio.pause();
    });
    container.classList.add("playing");
    button.setAttribute("aria-label", "Pause voice message");
  });
  audio.addEventListener("pause", () => {
    container.classList.remove("playing");
    button.setAttribute("aria-label", "Play voice message");
  });
  audio.addEventListener("ended", () => {
    container.classList.remove("playing");
    audio.currentTime = 0;
  });
  button.addEventListener("click", () => {
    if (audio.paused) {
      audio.play().catch(() => {
        duration.textContent = "Tap again";
      });
    } else {
      audio.pause();
    }
  });
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
  onlineCount.textContent = users.length;
  profileStatus.textContent = users.includes(username) ? "Online" : "Ready to connect";
  if (!users.length) {
    usersList.appendChild(createEmptyState("No one else is online in this room."));
    return;
  }
  users.forEach((name) => {
    const item = document.createElement("div");
    item.className = "user-chip";
    item.innerHTML = `<span class="dot"></span><span>${escapeHtml(name)}</span>`;
    usersList.appendChild(item);
  });
}

function renderFriends(friends) {
  friendsList.innerHTML = "";
  friendsCount.textContent = friends.length;
  if (!friends.length) {
    friendsList.appendChild(createEmptyState("No friends yet. Search and send requests to get started."));
    return;
  }
  friends.forEach((name) => {
    const canAddToGroup =
      currentRoomMeta &&
      currentRoomMeta.is_group &&
      !((currentRoomMeta.members || []).includes(name));
    const item = document.createElement("div");
    item.className = "user-chip";
    item.innerHTML = `
      <span class="avatar">${getInitials(name)}</span><span style="flex: 1;">${escapeHtml(name)}</span>
      ${canAddToGroup ? `<button type="button" data-add-friend="${escapeHtml(name)}">Add</button>` : ""}
      <button type="button" data-friend="${escapeHtml(name)}">Chat</button>
    `;
    friendsList.appendChild(item);
  });
}

function renderGroupFriendPicker(friends) {
  groupFriendPicker.innerHTML = "";
  if (!friends.length) {
    groupFriendPicker.appendChild(createEmptyState("Add friends first, then create a group."));
    return;
  }
  friends.forEach((name) => {
    const label = document.createElement("label");
    label.className = "friend-check";
    label.innerHTML = `
      <input type="checkbox" value="${escapeAttribute(name)}" />
      <span>${escapeHtml(name)}</span>
    `;
    groupFriendPicker.appendChild(label);
  });
}

roomsList.addEventListener("click", (event) => {
  const entry = event.target.closest(".room-chip");
  if (!entry) return;
  const selectedRoomId = entry.dataset.room;
  if (!selectedRoomId) return;
  const roomObj = cachedRooms.find((entry) => entry.room_id === selectedRoomId);
  if (roomObj) {
    selectRoom(roomObj);
  }
});

friendsList.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const friendToAdd = button.dataset.addFriend;
  if (friendToAdd) {
    await addFriendToCurrentGroup(friendToAdd);
    return;
  }
  const target = button.dataset.friend;
  if (!target || !token) return;
  const response = await fetch("/api/rooms/direct", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ target }),
  });
  const data = await response.json();
  if (data.ok) {
    await refreshRooms(data.room_id);
  }
});

async function addFriendToCurrentGroup(target) {
  if (!target || !token || !currentRoomMeta || !currentRoomMeta.is_group) return;
  const response = await fetch("/api/rooms/add-member", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ room_id: currentRoomMeta.room_id, target }),
  });
  const data = await response.json();
  if (data.ok) {
    addSystem(`${target} added to this group.`);
    await refreshRooms(currentRoomMeta.room_id);
  } else {
    addSystem(data.error || `Could not add ${target}.`);
  }
}

function renderRequests(incoming, outgoing) {
  requestsList.innerHTML = "";
  if (!incoming.length && !outgoing.length) {
    requestsList.appendChild(createEmptyState("No pending requests."));
    return;
  }
  incoming.forEach((name) => {
    const item = document.createElement("div");
    item.className = "user-chip request-incoming";
    item.innerHTML = `
      <span style="color: var(--green); font-weight: 800; flex: 1;">${escapeHtml(name)}</span>
      <button type="button" data-user="${escapeHtml(name)}" data-action="accept">Accept</button>
      <button type="button" data-user="${escapeHtml(name)}" data-action="ignore" class="secondary-btn">Ignore</button>
    `;
    requestsList.appendChild(item);
  });
  outgoing.forEach((name) => {
    const item = document.createElement("div");
    item.className = "user-chip request-outgoing";
    item.innerHTML = `
      <span style="color: var(--orange); font-weight: 700; flex: 1;">${escapeHtml(name)}</span>
      <span style="font-size: 12px; color: var(--muted);">Pending</span>
    `;
    requestsList.appendChild(item);
  });
}

function renderSearchResults(users) {
  searchResults.innerHTML = "";
  if (!users.length) {
    searchResults.appendChild(createEmptyState("No users found."));
    return;
  }
  users.forEach((user) => {
    const item = document.createElement("div");
    item.className = "user-chip";
    let buttonLabel = "Send Request";
    let action = "request";
    let disabled = false;
    let status = "";
    if (user.status === "friends") {
      buttonLabel = "Chat";
      action = "chat";
      status = "Friends";
    } else if (user.status === "requested") {
      buttonLabel = "Requested";
      disabled = true;
      status = "Pending";
    } else if (user.status === "incoming") {
      buttonLabel = "Check Requests";
      disabled = true;
      status = "Incoming";
    }
    item.innerHTML = `
      <span class="avatar">${getInitials(user.username)}</span>
      <div style="flex: 1;">
        <div style="font-weight: 700;">${escapeHtml(user.username)}</div>
        <div style="font-size: 12px; color: var(--muted);">${status}</div>
      </div>
      <button type="button" data-user="${escapeHtml(user.username)}" data-action="${action}" ${disabled ? "disabled" : ""}>${buttonLabel}</button>
    `;
    searchResults.appendChild(item);
  });
}

searchResults.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const target = button.dataset.user;
  const action = button.dataset.action;
  if (!target || button.disabled) return;
  if (action === "chat") {
    const response = await fetch("/api/rooms/direct", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Auth-Token": token },
      body: JSON.stringify({ target }),
    });
    const data = await response.json();
    if (data.ok) {
      await refreshRooms(data.room_id);
    }
  } else {
    await sendFriendRequest(target);
    await refreshFriendData();
    searchUsers(searchInput.value.trim());
  }
});

requestsList.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const requestor = button.dataset.user;
  const accept = button.dataset.action === "accept";
  if (!requestor) return;
  await respondFriendRequest(requestor, accept);
  await refreshFriendData();
  searchUsers(searchInput.value.trim());
});

async function sendFriendRequest(target) {
  if (!token) return;
  await fetch("/api/friends/request", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ target }),
  });
}

async function respondFriendRequest(requestor, accept) {
  if (!token) return;
  await fetch("/api/friends/respond", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ requestor, accept }),
  });
}

async function uploadFiles(files) {
  for (const file of files) {
    await uploadFile(file);
  }
}

function uploadFile(file, options = {}) {
  return new Promise((resolve) => {
    if (!token || !room) {
      addSystem("Select a conversation before sharing a file.");
      resolve();
      return;
    }
    const xhr = new XMLHttpRequest();
    const displayName = options.filename || file.webkitRelativePath || file.name;
    const kind = options.kind || "file";
    const url = `/upload?token=${encodeURIComponent(token)}&room=${encodeURIComponent(room)}&filename=${encodeURIComponent(displayName)}&kind=${encodeURIComponent(kind)}`;
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

async function startVoiceRecording() {
  if (!token || !room) {
    addSystem("Select a conversation before recording a voice message.");
    return;
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    voiceFallbackInput.click();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    voiceChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) {
        voiceChunks.push(event.data);
      }
    });
    mediaRecorder.addEventListener("stop", async () => {
      stream.getTracks().forEach((track) => track.stop());
      const mimeType = mediaRecorder.mimeType || "audio/webm";
      const extension = mimeType.includes("ogg") ? "ogg" : "webm";
      const voiceBlob = new Blob(voiceChunks, { type: mimeType });
      const stamp = new Date().toISOString().replaceAll(":", "-").split(".")[0];
      await uploadFile(voiceBlob, { filename: `voice-${stamp}.${extension}`, kind: "voice" });
      voiceChunks = [];
    });
    mediaRecorder.start();
    isRecordingVoice = true;
    voiceButton.classList.add("recording");
    voiceButton.innerHTML = "&#9632;";
    addSystem("Recording voice message...");
  } catch (error) {
    voiceFallbackInput.click();
  }
}

function stopVoiceRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  mediaRecorder.stop();
  isRecordingVoice = false;
  voiceButton.classList.remove("recording");
  voiceButton.innerHTML = "&#127908;";
}

function sendTyping(isTyping) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "typing", isTyping }));
}

function setStatus(text, online) {
  connectionStatus.textContent = text;
  connectionStatus.classList.toggle("online", online);
  if (username) {
    profileStatus.textContent = online ? "Online" : "Ready to connect";
  }
}

function updateProfile() {
  profileName.textContent = username || "Guest";
  profileAvatar.textContent = getInitials(username || "AIR Bridge");
  profileStatus.textContent = username ? "Ready to connect" : "Signed out";
}

function updateRoomHeader(title) {
  roomTitle.textContent = title;
  roomAvatar.textContent = title === "Select a conversation" ? "#" : getInitials(title);
}

function getRoomDisplayTitle(roomObj) {
  const rawTitle = roomObj.title || roomObj.room_id || "";
  if (roomObj.is_group) {
    return rawTitle.includes(roomObj.room_id) ? rawTitle : `${rawTitle} (${roomObj.room_id})`;
  }
  if (roomObj.peer) {
    return roomObj.peer;
  }
  if (Array.isArray(roomObj.members)) {
    const peer = roomObj.members.find((member) => member !== username);
    if (peer) return peer;
  }
  if (rawTitle.startsWith("Chat: ")) {
    const peer = rawTitle
      .replace("Chat: ", "")
      .split("+")
      .map((name) => name.trim())
      .find((name) => name && name !== username);
    if (peer) return peer;
  }
  return rawTitle;
}

function createEmptyState(text) {
  const emptyMsg = document.createElement("div");
  emptyMsg.className = "empty-state";
  emptyMsg.textContent = text;
  return emptyMsg;
}

function getInitials(value) {
  return String(value || "")
    .split(/[\s:+_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("") || "AB";
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

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function isImageFile(filename) {
  return /\.(apng|avif|bmp|gif|jpe?g|png|webp)$/i.test(String(filename || ""));
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainingSeconds}`;
}
