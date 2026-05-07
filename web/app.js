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
const profileButton = document.querySelector("#profileButton");
const notificationButton = document.querySelector("#notificationButton");
const notificationCount = document.querySelector("#notificationCount");
const chatNotificationButton = document.querySelector("#chatNotificationButton");
const chatNotificationCount = document.querySelector("#chatNotificationCount");
const profilePanel = document.querySelector("#profilePanel");
const closeProfilePanel = document.querySelector("#closeProfilePanel");
const profileAvatar = document.querySelector("#profileAvatar");
const profileName = document.querySelector("#profileName");
const profileStatus = document.querySelector("#profileStatus");
const profilePanelAvatar = document.querySelector("#profilePanelAvatar");
const profilePanelName = document.querySelector("#profilePanelName");
const profileRequestCount = document.querySelector("#profileRequestCount");
const profileFriendsCount = document.querySelector("#profileFriendsCount");
const roomAvatar = document.querySelector("#roomAvatar");
const roomInfoButton = document.querySelector("#roomInfoButton");
const mobileChatsButton = document.querySelector("#mobileChatsButton");
const roomInfoPanel = document.querySelector("#roomInfoPanel");
const closeInfoPanel = document.querySelector("#closeInfoPanel");
const infoTitle = document.querySelector("#infoTitle");
const infoAvatar = document.querySelector("#infoAvatar");
const infoName = document.querySelector("#infoName");
const infoMeta = document.querySelector("#infoMeta");
const groupInfoControls = document.querySelector("#groupInfoControls");
const groupDescriptionInput = document.querySelector("#groupDescriptionInput");
const saveDescriptionButton = document.querySelector("#saveDescriptionButton");
const shareGroupButton = document.querySelector("#shareGroupButton");
const infoMembersCount = document.querySelector("#infoMembersCount");
const infoMembersList = document.querySelector("#infoMembersList");
const infoAddMembers = document.querySelector("#infoAddMembers");
const showAddMembersButton = document.querySelector("#showAddMembersButton");
const infoAddMembersList = document.querySelector("#infoAddMembersList");
const roomDangerControls = document.querySelector("#roomDangerControls");
const deleteRoomButton = document.querySelector("#deleteRoomButton");
const deleteAccountButton = document.querySelector("#deleteAccountButton");
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
let cachedOutgoingInvites = [];
let currentRoomMeta = null;
let addMembersOpen = false;
let pendingRequestCount = 0;
let unreadMessages = {};
let seenMessages = {};
let roomPollTimer;
let pendingJoinRoomId = getJoinRoomIdFromUrl();

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
  syncLayoutState();

  updateProfile();
  updateRoomHeader("Select a conversation");
  joinPanel.classList.add("hidden");
  chatPanel.classList.remove("hidden");
  setStatus("Offline", false);
  messages.innerHTML = "";
  addSystem("Welcome! Search for friends, send requests, or create a group chat.");
  loadSeenMessages();
  await refreshFriendData();
  await refreshRooms();
  await handlePendingJoinLink();
  startRoomPolling();
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

profileButton.addEventListener("click", () => {
  openProfilePanel();
});

notificationButton.addEventListener("click", () => {
  openProfilePanel();
});

chatNotificationButton.addEventListener("click", () => {
  const unreadRoomId = Object.keys(unreadMessages)[0];
  const unreadRoom = cachedRooms.find((item) => item.room_id === unreadRoomId);
  if (unreadRoom) {
    selectRoom(unreadRoom);
  }
});

mobileChatsButton.addEventListener("click", () => {
  chatPanel.classList.toggle("mobile-sidebar-open");
});

closeProfilePanel.addEventListener("click", () => {
  profilePanel.classList.add("hidden");
});

roomInfoButton.addEventListener("click", () => {
  if (!currentRoomMeta) return;
  openRoomInfo();
});

closeInfoPanel.addEventListener("click", () => {
  roomInfoPanel.classList.add("hidden");
});

saveDescriptionButton.addEventListener("click", saveGroupDescription);
shareGroupButton.addEventListener("click", copyCurrentGroupLink);
deleteRoomButton.addEventListener("click", deleteCurrentGroup);
deleteAccountButton.addEventListener("click", deleteCurrentAccount);

showAddMembersButton.addEventListener("click", () => {
  addMembersOpen = !addMembersOpen;
  showAddMembersButton.textContent = addMembersOpen ? "Hide Add Members" : "Add Members";
  infoAddMembersList.classList.toggle("hidden", !addMembersOpen);
  renderInfoAddMembers();
});

infoAddMembersList.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const target = button.dataset.addFriend;
  if (target) {
    await addFriendToCurrentGroup(target);
    renderRoomInfo();
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
  await requestJoinRoom(roomId);
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
  resetSession();
});

function resetSession(notice = "") {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  token = "";
  username = "";
  room = "";
  syncLayoutState();
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
  cachedOutgoingInvites = [];
  currentRoomMeta = null;
  addMembersOpen = false;
  pendingRequestCount = 0;
  unreadMessages = {};
  seenMessages = {};
  stopRoomPolling();
  updateNotificationBadge();
  profilePanel.classList.add("hidden");
  roomInfoPanel.classList.add("hidden");
  updateProfile();
  updateRoomHeader("Select a conversation");
  setStatus("Offline", false);
  chatPanel.classList.add("hidden");
  joinPanel.classList.remove("hidden");
  joinNotice.textContent = notice || "Use your account credentials to login.";
}

window.addEventListener("load", async () => {
  const savedToken = localStorage.getItem("chatshareToken");
  const savedUsername = localStorage.getItem("chatshareUsername");
  if (savedToken && savedUsername) {
    token = savedToken;
    username = savedUsername;
    usernameInput.value = username;
    updateProfile();
    joinNotice.textContent = pendingJoinRoomId
      ? "Login to request access to the shared group."
      : "Enter your password and login.";
    joinPanel.classList.remove("hidden");
    chatPanel.classList.add("hidden");
  } else {
    updateProfile();
    if (pendingJoinRoomId) {
      joinNotice.textContent = "Login or register to request access to the shared group.";
    }
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
    updateUnreadFromRooms(rooms);
    renderRooms(rooms);
    const activeRoom = rooms.find((item) => item.room_id === room);
    if (activeRoom) {
      currentRoomMeta = activeRoom;
      markRoomSeen(activeRoom);
      updateRoomHeader(getRoomDisplayTitle(activeRoom));
      renderFriends(cachedFriends);
      renderRoomInfo();
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
    const unreadCount = unreadMessages[item.room_id] || 0;
    const entry = document.createElement("div");
    entry.className = `user-chip room-chip${current ? " active" : ""}${unreadCount > 0 ? " unread" : ""}`;
    entry.dataset.room = item.room_id;
    entry.innerHTML = `
      <span class="avatar">${getInitials(displayTitle)}</span>
      <div class="room-copy">
        <span class="room-name">${escapeHtml(displayTitle)}</span>
        <small>${escapeHtml(getRoomPreview(item))}</small>
      </div>
      <div class="room-side">
        ${item.last_message_time ? `<time>${escapeHtml(item.last_message_time)}</time>` : ""}
        ${unreadCount > 0 ? `<span class="unread-badge">${unreadCount}</span>` : ""}
      </div>
    `;
    roomsList.appendChild(entry);
  });
}

function selectRoom(roomObj) {
  if (!roomObj) return;
  if (!currentRoomMeta || currentRoomMeta.room_id !== roomObj.room_id) {
    addMembersOpen = false;
  }
  currentRoomMeta = roomObj;
  if (roomObj.room_id === room) {
    updateRoomHeader(getRoomDisplayTitle(roomObj));
    markRoomSeen(roomObj);
    renderRooms(cachedRooms);
    renderFriends(cachedFriends);
    renderRoomInfo();
    syncLayoutState();
    chatPanel.classList.remove("mobile-sidebar-open");
    return;
  }
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  room = roomObj.room_id;
  syncLayoutState();
  chatPanel.classList.remove("mobile-sidebar-open");
  markRoomSeen(roomObj);
  updateRoomHeader(getRoomDisplayTitle(roomObj));
  renderRooms(cachedRooms);
  renderFriends(cachedFriends);
  renderRoomInfo();
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
        addHistoryItem(item);
      });
      const lastHistoryMessage = data.messages[data.messages.length - 1];
      if (lastHistoryMessage?.id) {
        updateCachedRoomPreview(data.room || room, lastHistoryMessage);
        markRoomSeen({ room_id: data.room || room, last_message_id: lastHistoryMessage.id });
        renderRooms(cachedRooms);
      }
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
      cachedOutgoingInvites = data.outgoing_invite || [];
      renderFriends(cachedFriends);
      renderGroupFriendPicker(cachedFriends);
      renderRequests(
        data.incoming || [],
        data.outgoing || [],
        data.incoming_join || [],
        data.outgoing_join || [],
        data.incoming_invite || [],
        data.outgoing_invite || []
      );
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
    if (data.id) {
      updateCachedRoomPreview(room, {
        id: data.id,
        sender: data.sender,
        message: data.message,
        time: data.time,
      });
      const active = cachedRooms.find((item) => item.room_id === room);
      markRoomSeen({ ...(active || { room_id: room }), last_message_id: data.id });
      renderRooms(cachedRooms);
    }
  }

  if (data.type === "system") {
    addSystem(data.message);
  }

  if (data.type === "room_deleted") {
    addSystem(data.message || "This group was deleted.");
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.close();
    }
    room = "";
    currentRoomMeta = null;
    syncLayoutState();
    messages.innerHTML = "";
    usersList.innerHTML = "";
    onlineCount.textContent = "0";
    setStatus("Offline", false);
    updateRoomHeader("Select a conversation");
    refreshRooms();
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
    if (data.id) {
      updateCachedRoomPreview(room, {
        id: data.id,
        sender: data.sender,
        message: getFilePreviewText(data),
        time: data.time,
      });
      const active = cachedRooms.find((item) => item.room_id === room);
      markRoomSeen({ ...(active || { room_id: room }), last_message_id: data.id });
      renderRooms(cachedRooms);
    }
  }

  if (data.type === "history" && Array.isArray(data.messages)) {
    messages.innerHTML = "";
    data.messages.forEach((item) => {
      addHistoryItem(item);
    });
    const lastHistoryMessage = data.messages[data.messages.length - 1];
    if (lastHistoryMessage?.id) {
      updateCachedRoomPreview(data.room || room, lastHistoryMessage);
      markRoomSeen({ room_id: data.room || room, last_message_id: lastHistoryMessage.id });
      renderRooms(cachedRooms);
    }
    if (data.messages.length) {
      addSystem(`Loaded ${data.messages.length} saved messages.`);
    }
  }
}

function addHistoryItem(item) {
  if (item.type === "file") {
    addFileMessage(item);
    return;
  }
  addMessage({ sender: item.sender, text: item.message, time: item.time, mine: item.sender === username });
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
  profileFriendsCount.textContent = friends.length;
  if (!friends.length) {
    friendsList.appendChild(createEmptyState("No friends yet. Search and send requests to get started."));
    return;
  }
  friends.forEach((name) => {
    const canAddToGroup =
      currentRoomMeta?.is_group && !getRoomMembers(currentRoomMeta).includes(name);
    const item = document.createElement("div");
    item.className = "user-chip";
    item.innerHTML = `
      <span class="avatar">${getInitials(name)}</span><span style="flex: 1;">${escapeHtml(name)}</span>
      ${canAddToGroup ? `<button type="button" data-add-friend="${escapeAttribute(name)}">Add</button>` : ""}
      <button type="button" data-friend="${escapeHtml(name)}">Chat</button>
      <button type="button" data-remove-friend="${escapeAttribute(name)}" class="secondary-btn">Unfriend</button>
    `;
    friendsList.appendChild(item);
  });
}

function openProfilePanel() {
  updateProfile();
  profilePanel.classList.remove("hidden");
  if (pendingRequestCount > 0) {
    refreshFriendData();
  }
}

function openRoomInfo() {
  renderRoomInfo();
  roomInfoPanel.classList.remove("hidden");
}

function renderRoomInfo() {
  if (!currentRoomMeta) {
    infoTitle.textContent = "Conversation";
    infoAvatar.textContent = "#";
    infoName.textContent = "Select a conversation";
    infoMeta.textContent = "No room selected";
    infoMembersCount.textContent = "0";
    infoMembersList.innerHTML = "";
    infoAddMembersList.innerHTML = "";
    groupInfoControls.classList.add("hidden");
    infoAddMembers.classList.add("hidden");
    roomDangerControls.classList.add("hidden");
    return;
  }

  currentRoomMeta = getFreshCurrentRoom();
  const title = getRoomDisplayTitle(currentRoomMeta);
  const members = getRoomMembers(currentRoomMeta);
  const isGroup = Boolean(currentRoomMeta.is_group);
  infoTitle.textContent = isGroup ? "Group Info" : "Contact Info";
  infoAvatar.textContent = getInitials(title);
  infoName.textContent = title;
  infoMeta.textContent = isGroup ? `${members.length} members` : "Direct chat";
  infoMembersCount.textContent = members.length;
  infoMembersList.innerHTML = "";
  members.forEach((member) => {
    const item = document.createElement("div");
    item.className = "user-chip member-chip";
    item.innerHTML = `
      <span class="avatar">${getInitials(member)}</span>
      <span style="flex: 1;">${escapeHtml(member)}</span>
      ${member === username ? `<span class="room-kind">You</span>` : ""}
    `;
    infoMembersList.appendChild(item);
  });

  groupInfoControls.classList.toggle("hidden", !isGroup);
  infoAddMembers.classList.toggle("hidden", !isGroup);
  roomDangerControls.classList.toggle("hidden", !(isGroup && currentRoomMeta.is_owner));
  groupDescriptionInput.value = currentRoomMeta.description || "";
  if (!isGroup) {
    addMembersOpen = false;
  }
  showAddMembersButton.textContent = addMembersOpen ? "Hide Add Members" : "Add Members";
  infoAddMembersList.classList.toggle("hidden", !addMembersOpen);
  renderInfoAddMembers();
}

function renderInfoAddMembers() {
  infoAddMembersList.innerHTML = "";
  if (!currentRoomMeta || !currentRoomMeta.is_group) return;
  const members = getRoomMembers(currentRoomMeta);
  const pendingInviteTargets = new Set(
    cachedOutgoingInvites
      .filter((invite) => currentRoomMeta && invite.room_id === currentRoomMeta.room_id)
      .map((invite) => invite.target)
  );
  const addableFriends = cachedFriends.filter((friend) => !members.includes(friend));
  if (!addableFriends.length) {
    infoAddMembersList.appendChild(createEmptyState("All friends are already in this group."));
    return;
  }
  addableFriends.forEach((friend) => {
    const pending = pendingInviteTargets.has(friend);
    const item = document.createElement("div");
    item.className = "user-chip";
    item.innerHTML = `
      <span class="avatar">${getInitials(friend)}</span>
      <span style="flex: 1;">${escapeHtml(friend)}</span>
      <button type="button" data-add-friend="${escapeAttribute(friend)}" ${pending ? "disabled" : ""}>${pending ? "Pending" : "Add"}</button>
    `;
    infoAddMembersList.appendChild(item);
  });
}

function getFreshCurrentRoom() {
  if (!currentRoomMeta) return null;
  return cachedRooms.find((item) => item.room_id === currentRoomMeta.room_id) || currentRoomMeta;
}

function getRoomMembers(roomObj) {
  const members = Array.isArray(roomObj?.members) ? [...roomObj.members] : [];
  if (roomObj?.is_group && username && !members.includes(username)) {
    members.unshift(username);
  }
  return members;
}

async function saveGroupDescription() {
  if (!token || !currentRoomMeta || !currentRoomMeta.is_group) return;
  const description = groupDescriptionInput.value.trim();
  const response = await fetch("/api/rooms/description", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ room_id: currentRoomMeta.room_id, description }),
  });
  const data = await response.json();
  if (data.ok) {
    addSystem("Group description saved.");
    await refreshRooms(currentRoomMeta.room_id);
  } else {
    addSystem(data.error || "Could not save group description.");
  }
}

async function requestJoinRoom(roomId, fromLink = false) {
  const targetRoomId = String(roomId || "").trim();
  if (!targetRoomId || !token) return;
  const response = await fetch("/api/rooms/join", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ room_id: targetRoomId }),
  });
  const data = await response.json();
  if (data.ok) {
    roomIdInput.value = "";
    if (data.pending) {
      addSystem(data.message || "Join request sent. Wait for a group member to accept it.");
      await refreshFriendData();
    } else {
      await refreshRooms(data.room_id);
    }
    if (fromLink) {
      pendingJoinRoomId = "";
      clearJoinRoomIdFromUrl();
    }
  } else {
    addSystem(data.error || "Could not request to join room.");
    if (fromLink) {
      pendingJoinRoomId = "";
      clearJoinRoomIdFromUrl();
    }
  }
}

async function handlePendingJoinLink() {
  if (!pendingJoinRoomId || !token) return;
  await requestJoinRoom(pendingJoinRoomId, true);
}

async function copyCurrentGroupLink() {
  if (!currentRoomMeta?.is_group) return;
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  url.searchParams.set("join", currentRoomMeta.room_id);
  const link = url.toString();
  try {
    await navigator.clipboard.writeText(link);
    addSystem("Group link copied.");
  } catch (error) {
    window.prompt("Copy group link", link);
  }
}

function getJoinRoomIdFromUrl() {
  return new URLSearchParams(window.location.search).get("join") || "";
}

function clearJoinRoomIdFromUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete("join");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

async function deleteCurrentGroup() {
  if (!token || !currentRoomMeta || !currentRoomMeta.is_group || !currentRoomMeta.is_owner) return;
  const title = getRoomDisplayTitle(currentRoomMeta);
  if (!confirm(`Delete group "${title}"? Messages, members, invites, and requests for this group will be removed from the database.`)) {
    return;
  }
  const response = await fetch("/api/rooms/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ room_id: currentRoomMeta.room_id }),
  });
  const data = await response.json();
  if (!data.ok) {
    addSystem(data.error || "Could not delete group.");
    return;
  }
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  delete seenMessages[currentRoomMeta.room_id];
  saveSeenMessages();
  room = "";
  currentRoomMeta = null;
  syncLayoutState();
  messages.innerHTML = "";
  usersList.innerHTML = "";
  onlineCount.textContent = "0";
  roomInfoPanel.classList.add("hidden");
  updateRoomHeader("Select a conversation");
  setStatus("Offline", false);
  await refreshRooms();
}

async function deleteCurrentAccount() {
  if (!token || !username) return;
  if (!confirm("Delete your account? Your user, sessions, friendships, requests, invites, and sent messages will be removed from the database.")) {
    return;
  }
  const response = await fetch("/api/account/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({}),
  });
  const data = await response.json();
  if (data.ok) {
    resetSession("Account deleted.");
  } else {
    addSystem(data.error || "Could not delete account.");
  }
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
  const friendToRemove = button.dataset.removeFriend;
  if (friendToRemove) {
    await removeFriendship(friendToRemove, "Friend removed.");
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
  const inviteButton = infoAddMembersList.querySelector(`[data-add-friend="${CSS.escape(target)}"]`);
  if (inviteButton) {
    inviteButton.disabled = true;
    inviteButton.textContent = "Sending";
  }
  const response = await fetch("/api/rooms/add-member", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ room_id: currentRoomMeta.room_id, target }),
  });
  const data = await response.json();
  if (data.ok) {
    addSystem(data.message || `Invite sent to ${target}.`);
    await refreshFriendData();
    addMembersOpen = true;
    renderRoomInfo();
  } else {
    addSystem(data.error || `Could not add ${target}.`);
    if (inviteButton) {
      inviteButton.disabled = false;
      inviteButton.textContent = "Add";
    }
  }
}

function renderRequests(incoming, outgoing, incomingJoin = [], outgoingJoin = [], incomingInvite = [], outgoingInvite = []) {
  requestsList.innerHTML = "";
  pendingRequestCount = incoming.length + incomingJoin.length + incomingInvite.length;
  profileRequestCount.textContent = pendingRequestCount;
  updateNotificationBadge();
  if (!incoming.length && !outgoing.length && !incomingJoin.length && !outgoingJoin.length && !incomingInvite.length && !outgoingInvite.length) {
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
      <button type="button" data-withdraw-friend="${escapeAttribute(name)}" class="secondary-btn">Withdraw</button>
    `;
    requestsList.appendChild(item);
  });
  incomingJoin.forEach((request) => {
    const item = document.createElement("div");
    item.className = "user-chip request-incoming";
    item.innerHTML = `
      <div style="flex: 1;">
        <div style="color: var(--green); font-weight: 800;">${escapeHtml(request.requestor)}</div>
        <div style="font-size: 12px; color: var(--muted);">wants to join ${escapeHtml(request.title || request.room_id)}</div>
      </div>
      <button type="button" data-join-room="${escapeAttribute(request.room_id)}" data-user="${escapeAttribute(request.requestor)}" data-action="accept-join">Accept</button>
      <button type="button" data-join-room="${escapeAttribute(request.room_id)}" data-user="${escapeAttribute(request.requestor)}" data-action="ignore-join" class="secondary-btn">Ignore</button>
    `;
    requestsList.appendChild(item);
  });
  outgoingJoin.forEach((request) => {
    const item = document.createElement("div");
    item.className = "user-chip request-outgoing";
    item.innerHTML = `
      <div style="flex: 1;">
        <div style="color: var(--orange); font-weight: 800;">${escapeHtml(request.title || request.room_id)}</div>
        <div style="font-size: 12px; color: var(--muted);">Join request pending</div>
      </div>
    `;
    requestsList.appendChild(item);
  });
  incomingInvite.forEach((invite) => {
    const item = document.createElement("div");
    item.className = "user-chip request-incoming";
    item.innerHTML = `
      <div style="flex: 1;">
        <div style="color: var(--green); font-weight: 800;">${escapeHtml(invite.title || invite.room_id)}</div>
        <div style="font-size: 12px; color: var(--muted);">${escapeHtml(invite.inviter)} invited you</div>
      </div>
      <button type="button" data-invite-room="${escapeAttribute(invite.room_id)}" data-inviter="${escapeAttribute(invite.inviter)}" data-action="accept-invite">Accept</button>
      <button type="button" data-invite-room="${escapeAttribute(invite.room_id)}" data-inviter="${escapeAttribute(invite.inviter)}" data-action="ignore-invite" class="secondary-btn">Ignore</button>
    `;
    requestsList.appendChild(item);
  });
  outgoingInvite.forEach((invite) => {
    const item = document.createElement("div");
    item.className = "user-chip request-outgoing";
    item.innerHTML = `
      <div style="flex: 1;">
        <div style="color: var(--orange); font-weight: 800;">${escapeHtml(invite.target)}</div>
        <div style="font-size: 12px; color: var(--muted);">Invite pending for ${escapeHtml(invite.title || invite.room_id)}</div>
      </div>
    `;
    requestsList.appendChild(item);
  });
}

function updateNotificationBadge() {
  notificationCount.textContent = pendingRequestCount;
  notificationButton.classList.toggle("muted", pendingRequestCount === 0);
  const unreadTotal = getUnreadTotal();
  chatNotificationCount.textContent = unreadTotal;
  chatNotificationButton.classList.toggle("muted", unreadTotal === 0);
}

function startRoomPolling() {
  stopRoomPolling();
  roomPollTimer = setInterval(() => {
    if (token) {
      refreshRooms();
      refreshFriendData();
    }
  }, 5000);
}

function stopRoomPolling() {
  if (roomPollTimer) {
    clearInterval(roomPollTimer);
    roomPollTimer = undefined;
  }
}

function loadSeenMessages() {
  try {
    seenMessages = JSON.parse(localStorage.getItem(getSeenStorageKey()) || "{}");
  } catch (error) {
    seenMessages = {};
  }
}

function saveSeenMessages() {
  localStorage.setItem(getSeenStorageKey(), JSON.stringify(seenMessages));
}

function getSeenStorageKey() {
  return `chatshareSeen:${username || "guest"}`;
}

function updateUnreadFromRooms(rooms) {
  const nextUnread = {};
  rooms.forEach((item) => {
    const lastId = Number(item.last_message_id || 0);
    const seenId = Number(seenMessages[item.room_id] || 0);
    const sentByMe = item.last_message_sender === username;
    if (sentByMe && lastId > seenId) {
      seenMessages[item.room_id] = lastId;
      return;
    }
    if (item.room_id !== room && lastId > seenId) {
      nextUnread[item.room_id] = 1;
    }
  });
  unreadMessages = nextUnread;
  saveSeenMessages();
  updateNotificationBadge();
}

function markRoomSeen(roomObj) {
  if (!roomObj?.room_id) return;
  const lastId = Number(roomObj.last_message_id || 0);
  if (lastId > 0) {
    seenMessages[roomObj.room_id] = Math.max(Number(seenMessages[roomObj.room_id] || 0), lastId);
    saveSeenMessages();
  }
  delete unreadMessages[roomObj.room_id];
  updateNotificationBadge();
}

function getUnreadTotal() {
  return Object.values(unreadMessages).reduce((total, count) => total + Number(count || 0), 0);
}

function getRoomPreview(item) {
  if (!item.last_message) return item.is_group ? "No group messages yet" : "No messages yet";
  const prefix = item.last_message_sender === username ? "You: " : item.last_message_sender ? `${item.last_message_sender}: ` : "";
  return `${prefix}${item.last_message}`;
}

function updateCachedRoomPreview(roomId, message) {
  const targetRoom = cachedRooms.find((item) => item.room_id === roomId);
  if (!targetRoom || !message) return;
  targetRoom.last_message_id = message.id || targetRoom.last_message_id || 0;
  targetRoom.last_message_sender = message.sender || "";
  targetRoom.last_message = message.type === "file" ? getFilePreviewText(message) : message.message || "";
  targetRoom.last_message_time = message.time || "";
}

function getFilePreviewText(item) {
  if (item.kind === "voice") return "Voice message";
  return item.filename || "Shared file";
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
  if (button.dataset.withdrawFriend) {
    await removeFriendship(button.dataset.withdrawFriend, "Request withdrawn.");
    return;
  }
  if (button.dataset.joinRoom) {
    const acceptJoin = button.dataset.action === "accept-join";
    await respondJoinRequest(button.dataset.joinRoom, button.dataset.user, acceptJoin);
    await refreshFriendData();
    await refreshRooms(room);
    return;
  }
  if (button.dataset.inviteRoom) {
    const acceptInvite = button.dataset.action === "accept-invite";
    const inviteRoom = button.dataset.inviteRoom;
    await respondInviteRequest(inviteRoom, button.dataset.inviter, acceptInvite);
    await refreshFriendData();
    await refreshRooms(acceptInvite ? inviteRoom : room);
    return;
  }
  const requestor = button.dataset.user;
  const accept = button.dataset.action === "accept";
  if (!requestor) return;
  await respondFriendRequest(requestor, accept);
  await refreshFriendData();
  searchUsers(searchInput.value.trim());
});

async function respondJoinRequest(roomId, requestor, accept) {
  if (!token || !roomId || !requestor) return;
  await fetch("/api/rooms/respond-join", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ room_id: roomId, requestor, accept }),
  });
}

async function respondInviteRequest(roomId, inviter, accept) {
  if (!token || !roomId || !inviter) return;
  await fetch("/api/rooms/respond-invite", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ room_id: roomId, inviter, accept }),
  });
}

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

async function removeFriendship(target, message) {
  if (!token || !target) return;
  const response = await fetch("/api/friends/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ target }),
  });
  const data = await response.json();
  if (data.ok) {
    addSystem(message || "Updated friend list.");
    await refreshFriendData();
    await refreshRooms(room);
    if (searchInput.value.trim()) {
      searchUsers(searchInput.value.trim());
    }
  } else {
    addSystem("Could not update friend request.");
  }
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
  profilePanelName.textContent = username || "Guest";
  profilePanelAvatar.textContent = getInitials(username || "AIR Bridge");
  profileStatus.textContent = username ? "Ready to connect" : "Signed out";
}

function updateRoomHeader(title) {
  roomTitle.textContent = title;
  roomAvatar.textContent = title === "Select a conversation" ? "#" : getInitials(title);
}

function syncLayoutState() {
  chatPanel.classList.toggle("room-open", Boolean(room));
  if (!room) {
    chatPanel.classList.remove("mobile-sidebar-open");
  }
}

function getRoomDisplayTitle(roomObj) {
  const rawTitle = roomObj.title || roomObj.room_id || "";
  if (roomObj.is_group) {
    return rawTitle;
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
