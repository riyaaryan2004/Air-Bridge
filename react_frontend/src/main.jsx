import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api/client.js";
import "./styles.css";

function initials(value) {
  return String(value || "AB")
    .split(/[\s:+_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("") || "AB";
}

function App() {
  const [token, setToken] = useState(localStorage.getItem("chatshareToken") || "");
  const [username, setUsername] = useState(localStorage.getItem("chatshareUsername") || "");
  const [loginName, setLoginName] = useState(username);
  const [password, setPassword] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [notice, setNotice] = useState("Use your account credentials to login.");
  const [rooms, setRooms] = useState([]);
  const [currentRoom, setCurrentRoom] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [friends, setFriends] = useState([]);
  const [friendData, setFriendData] = useState({});
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [groupTitle, setGroupTitle] = useState("");
  const [groupMembers, setGroupMembers] = useState([]);
  const [joinId, setJoinId] = useState("");
  const [pendingJoinId, setPendingJoinId] = useState(() => getJoinIdFromUrl());
  const [onlineUsers, setOnlineUsers] = useState([]);
  const [typingLine, setTypingLine] = useState("");
  const [status, setStatus] = useState("Offline");
  const [profileOpen, setProfileOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [addMembersOpen, setAddMembersOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [seenMessages, setSeenMessages] = useState(() => loadSeen(username));
  const socketRef = useRef(null);
  const messagesRef = useRef(null);
  const typingTimerRef = useRef(null);

  const activeRoom = useMemo(
    () => rooms.find((room) => room.room_id === currentRoom?.room_id) || currentRoom,
    [rooms, currentRoom]
  );
  const unreadMessages = useMemo(() => {
    const next = {};
    rooms.forEach((room) => {
      const lastId = Number(room.last_message_id || 0);
      const seenId = Number(seenMessages[room.room_id] || 0);
      if (room.room_id !== activeRoom?.room_id && room.last_message_sender !== username && lastId > seenId) {
        next[room.room_id] = 1;
      }
    });
    return next;
  }, [rooms, seenMessages, activeRoom, username]);
  const requestCount =
    (friendData.incoming || []).length +
    (friendData.incoming_join || []).length +
    (friendData.incoming_invite || []).length;

  useEffect(() => {
    if (!token) return;
    refreshFriendData();
    refreshRooms();
    const timer = setInterval(() => {
      refreshFriendData();
      refreshRooms();
    }, 5000);
    return () => clearInterval(timer);
  }, [token]);

  useEffect(() => {
    if (!token || !pendingJoinId) return;
    requestJoinById(pendingJoinId, true);
  }, [token, pendingJoinId]);

  useEffect(() => {
    localStorage.setItem(seenKey(username), JSON.stringify(seenMessages));
  }, [seenMessages, username]);

  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight });
  }, [messages]);

  useEffect(() => {
    if (!token || !activeRoom) return;
    socketRef.current?.close();
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/ws?token=${encodeURIComponent(token)}&room=${encodeURIComponent(activeRoom.room_id)}`);
    socketRef.current = socket;
    setStatus("Connecting");
    socket.addEventListener("open", () => setStatus("Online"));
    socket.addEventListener("close", () => setStatus("Offline"));
    socket.addEventListener("error", () => setStatus("Offline"));
    socket.addEventListener("message", (event) => handleSocketMessage(JSON.parse(event.data)));
    return () => socket.close();
  }, [token, activeRoom?.room_id]);

  function handleSocketMessage(data) {
    if (data.type === "history") {
      setMessages((data.messages || []).map(normalizeHistoryMessage));
      const last = data.messages?.[data.messages.length - 1];
      if (last?.id) markSeen({ room_id: data.room || activeRoom?.room_id, last_message_id: last.id });
    }
    if (data.type === "chat") {
      setMessages((items) => [...items, {
        id: data.id,
        sender: data.sender,
        text: data.message,
        time: data.time,
        kind: "chat"
      }]);
      refreshRooms();
      markSeen({ room_id: activeRoom?.room_id, last_message_id: data.id });
    }
    if (data.type === "file") {
      setMessages((items) => [...items, { ...data, id: data.id || `${Date.now()}-${data.filename}`, kind: data.kind || "file" }]);
      refreshRooms();
      markSeen({ room_id: activeRoom?.room_id, last_message_id: data.id });
    }
    if (data.type === "presence") {
      setOnlineUsers(data.users || []);
      addSystem(data.message);
    }
    if (data.type === "typing") {
      setTypingLine(data.isTyping ? `${data.sender} is typing...` : "");
    }
    if (data.type === "system") {
      addSystem(data.message);
    }
    if (data.type === "room_deleted") {
      addSystem(data.message || "This group was deleted.");
      setCurrentRoom(null);
      setMessages([]);
      refreshRooms();
    }
  }

  function addSystem(message) {
    if (!message) return;
    setMessages((items) => [...items, { id: `${Date.now()}-${Math.random()}`, kind: "system", text: message }]);
  }

  function markSeen(room) {
    if (!room?.room_id || !room.last_message_id) return;
    setSeenMessages((items) => ({
      ...items,
      [room.room_id]: Math.max(Number(items[room.room_id] || 0), Number(room.last_message_id || 0))
    }));
  }

  async function authenticate(event) {
    event.preventDefault();
    const data = await api(`/api/${isRegister ? "register" : "login"}`, {
      method: "POST",
      body: JSON.stringify({ username: loginName, password })
    });
    if (!data.ok) {
      setNotice(data.error || "Login failed.");
      return;
    }
    localStorage.setItem("chatshareToken", data.token);
    localStorage.setItem("chatshareUsername", data.username);
    setToken(data.token);
    setUsername(data.username);
    setSeenMessages(loadSeen(data.username));
    setCurrentRoom(null);
  }

  function logout(message = "Use your account credentials to login.") {
    socketRef.current?.close();
    localStorage.removeItem("chatshareToken");
    localStorage.removeItem("chatshareUsername");
    setToken("");
    setUsername("");
    setPassword("");
    setRooms([]);
    setFriends([]);
    setFriendData({});
    setCurrentRoom(null);
    setMessages([]);
    setNotice(message);
  }

  async function refreshRooms(selectRoomId) {
    const data = await api("/api/rooms");
    const nextRooms = data.rooms || [];
    setRooms(nextRooms);
    if (activeRoom) {
      const updatedActive = nextRooms.find((room) => room.room_id === activeRoom.room_id);
      if (updatedActive) {
        setCurrentRoom(updatedActive);
        markSeen(updatedActive);
      }
    }
    if (selectRoomId) {
      const selected = nextRooms.find((room) => room.room_id === selectRoomId);
      if (selected) selectRoom(selected);
    }
    return nextRooms;
  }

  async function refreshFriendData() {
    const data = await api("/api/friends");
    setFriendData(data);
    setFriends(data.friends || []);
  }

  function selectRoom(room) {
    setCurrentRoom(room);
    setMessages([]);
    setInfoOpen(false);
    setMobileSidebarOpen(false);
    markSeen(room);
  }

  function sendMessage(event) {
    event.preventDefault();
    const message = text.trim();
    if (!message || socketRef.current?.readyState !== WebSocket.OPEN) return;
    socketRef.current.send(JSON.stringify({ type: "chat", message }));
    socketRef.current.send(JSON.stringify({ type: "typing", isTyping: false }));
    setText("");
  }

  function sendTyping() {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return;
    socketRef.current.send(JSON.stringify({ type: "typing", isTyping: true }));
    clearTimeout(typingTimerRef.current);
    typingTimerRef.current = setTimeout(() => {
      socketRef.current?.send(JSON.stringify({ type: "typing", isTyping: false }));
    }, 900);
  }

  async function uploadFiles(files) {
    if (!activeRoom) {
      addSystem("Select a conversation before sharing a file.");
      return;
    }
    for (const file of files) {
      await fetch(`/upload?token=${encodeURIComponent(token)}&room=${encodeURIComponent(activeRoom.room_id)}&filename=${encodeURIComponent(file.name)}&kind=file`, {
        method: "POST",
        body: file
      });
    }
  }

  async function searchUsers() {
    if (!search.trim()) {
      setSearchResults([]);
      return;
    }
    const data = await api(`/api/users?search=${encodeURIComponent(search.trim())}`);
    setSearchResults(data.users || []);
  }

  async function createGroup() {
    if (!groupTitle.trim()) return;
    const data = await api("/api/rooms", {
      method: "POST",
      body: JSON.stringify({ title: groupTitle, members: groupMembers })
    });
    if (data.ok) {
      setGroupTitle("");
      setGroupMembers([]);
      refreshRooms(data.room_id);
    }
  }

  async function requestJoinById(roomId, fromLink = false) {
    const cleanRoomId = String(roomId || "").trim();
    if (!cleanRoomId) return;
    const data = await post("/api/rooms/join", { room_id: cleanRoomId }, true);
    if (data.ok) {
      setJoinId("");
      if (data.pending) addSystem(data.message || "Join request sent. Wait for a group member to accept it.");
      if (!data.pending && data.room_id) await refreshRooms(data.room_id);
      if (fromLink) {
        setPendingJoinId("");
        clearJoinParam();
      }
    } else if (fromLink) {
      addSystem(data.error || "Could not request to join this group.");
      setPendingJoinId("");
      clearJoinParam();
    }
  }

  async function post(path, body, after = true) {
    const data = await api(path, { method: "POST", body: JSON.stringify(body) });
    if (!data.ok && data.error) addSystem(data.error);
    if (after) {
      await refreshFriendData();
      await refreshRooms(data.room_id || activeRoom?.room_id);
    }
    return data;
  }

  async function deleteGroup() {
    if (!activeRoom?.is_owner || !confirm(`Delete group "${activeRoom.title}"?`)) return;
    const data = await api("/api/rooms/delete", {
      method: "POST",
      body: JSON.stringify({ room_id: activeRoom.room_id })
    });
    if (data.ok) {
      setCurrentRoom(null);
      setInfoOpen(false);
      setMessages([]);
      refreshRooms();
    } else {
      addSystem(data.error || "Could not delete group.");
    }
  }

  async function deleteAccount() {
    if (!confirm("Delete your account and remove it from the local database?")) return;
    const data = await api("/api/account/delete", { method: "POST", body: JSON.stringify({}) });
    if (data.ok) logout("Account deleted.");
  }

  if (!token) {
    return (
      <main className="shell login-shell">
        <section className="join-panel">
          <div className="brand">
            <div className="brand-mark">AB</div>
            <div>
              <h1>AIR-Bridge</h1>
              <p>React UI with Python backend</p>
            </div>
          </div>
          <form className="join-form" onSubmit={authenticate}>
            <label>Username<input value={loginName} onChange={(event) => setLoginName(event.target.value)} maxLength={24} required /></label>
            <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} maxLength={64} required /></label>
            <button>{isRegister ? "Register" : "Login"}</button>
            <button type="button" className="secondary" onClick={() => setIsRegister(!isRegister)}>
              {isRegister ? "Already have an account? Login" : "Register New Account"}
            </button>
            <div className="notice">{notice}</div>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <section className={`chat-panel ${activeRoom ? "room-open" : ""} ${mobileSidebarOpen ? "mobile-sidebar-open" : ""}`}>
        <aside className="people">
          <div className="profile-card">
            <button className="profile-main" onClick={() => setProfileOpen(true)}>
              <span className="avatar large">{initials(username)}</span>
              <span><strong>{username}</strong><small>{status}</small></span>
            </button>
            <button className={`notify-button ${requestCount ? "" : "muted"}`} onClick={() => setProfileOpen(true)}>!<strong>{requestCount}</strong></button>
            <button className={`notify-button chat-notify ${Object.keys(unreadMessages).length ? "" : "muted"}`} onClick={() => {
              const first = rooms.find((room) => unreadMessages[room.room_id]);
              if (first) selectRoom(first);
            }}>#<strong>{Object.keys(unreadMessages).length}</strong></button>
            <button className="icon-button" onClick={() => logout()}>Logout</button>
          </div>

          <h3>Conversations</h3>
          <div className="users-list">
            {rooms.map((room) => (
              <button key={room.room_id} className={`room-chip ${activeRoom?.room_id === room.room_id ? "active" : ""}`} onClick={() => selectRoom(room)}>
                <span className="avatar">{initials(room.title)}</span>
                <span className="room-copy"><strong>{room.title}</strong><small>{preview(room, username)}</small></span>
                {unreadMessages[room.room_id] ? <b className="unread-badge">1</b> : null}
              </button>
            ))}
          </div>

          <h3>New Group</h3>
          <input value={groupTitle} onChange={(event) => setGroupTitle(event.target.value)} placeholder="Group name" />
          <div className="group-picker">
            {friends.map((friend) => (
              <label key={friend}>
                <input type="checkbox" checked={groupMembers.includes(friend)} onChange={(event) => {
                  setGroupMembers((items) => event.target.checked ? [...items, friend] : items.filter((item) => item !== friend));
                }} />
                <span>{friend}</span>
              </label>
            ))}
          </div>
          <button onClick={createGroup}>Create</button>

          <h3>Join by ID</h3>
          <input value={joinId} onChange={(event) => setJoinId(event.target.value)} placeholder="Paste room ID" />
          <button onClick={() => requestJoinById(joinId)}>Join</button>
        </aside>

        {profileOpen && (
          <ProfilePanel
            username={username}
            friends={friends}
            friendData={friendData}
            search={search}
            setSearch={setSearch}
            searchUsers={searchUsers}
            searchResults={searchResults}
            activeRoom={activeRoom}
            onlineUsers={onlineUsers}
            post={post}
            close={() => setProfileOpen(false)}
            deleteAccount={deleteAccount}
          />
        )}

        <section className="conversation">
          <header className="topbar">
            <button className="mobile-chats-button" type="button" onClick={() => setMobileSidebarOpen((open) => !open)}>Chats</button>
            <button className="conversation-heading" onClick={() => activeRoom && setInfoOpen(true)}>
              <span className="avatar">{initials(activeRoom?.title || "#")}</span>
              <span><small>Conversation</small><strong>{activeRoom?.title || "Select a conversation"}</strong></span>
            </button>
            <span className={`status ${status === "Online" ? "online" : ""}`}>{status}</span>
          </header>

          <div className="messages" ref={messagesRef}>
            {messages.map((message) => <Message key={message.id} item={message} username={username} />)}
          </div>
          <div className="typing-line">{typingLine}</div>
          <form className="composer" onSubmit={sendMessage}>
            <label className="file-btn">+
              <input type="file" multiple onChange={(event) => uploadFiles(event.target.files)} />
            </label>
            <input disabled={!activeRoom} value={text} onChange={(event) => {
              setText(event.target.value);
              sendTyping();
            }} placeholder="Type a message..." />
            <button disabled={!activeRoom}>Send</button>
          </form>
        </section>

        {infoOpen && activeRoom && (
          <RoomInfo
            room={activeRoom}
            friends={friends}
            friendData={friendData}
            addMembersOpen={addMembersOpen}
            setAddMembersOpen={setAddMembersOpen}
            post={post}
            close={() => setInfoOpen(false)}
            deleteGroup={deleteGroup}
            addSystem={addSystem}
          />
        )}
      </section>
    </main>
  );
}

function ProfilePanel({ username, friends, friendData, search, setSearch, searchUsers, searchResults, activeRoom, onlineUsers, post, close, deleteAccount }) {
  return (
    <aside className="info-panel profile-panel">
      <div className="info-head"><button className="icon-button" onClick={close}>Close</button><h3>People</h3></div>
      <div className="info-profile"><span className="avatar large">{initials(username)}</span><strong>{username}</strong><span>{friends.length} friends</span></div>
      <section className="info-section">
        <h3>Search Users</h3>
        <div className="search-row"><input value={search} onChange={(event) => setSearch(event.target.value)} /><button onClick={searchUsers}>Search</button></div>
        {searchResults.map((user) => (
          <div className="user-chip" key={user.username}>
            <span className="avatar">{initials(user.username)}</span><strong>{user.username}</strong>
            <button disabled={user.status !== "none"} onClick={() => post("/api/friends/request", { target: user.username })}>{user.status === "none" ? "Request" : user.status}</button>
          </div>
        ))}
      </section>
      <section className="info-section">
        <h3>Requests</h3>
        {(friendData.incoming || []).map((name) => <RequestRow key={name} title={name} accept={() => post("/api/friends/respond", { requestor: name, accept: true })} ignore={() => post("/api/friends/respond", { requestor: name, accept: false })} />)}
        {(friendData.outgoing || []).map((name) => (
          <div className="user-chip request-outgoing" key={name}>
            <strong>{name}</strong>
            <small>Pending</small>
            <button className="secondary-btn" onClick={() => post("/api/friends/remove", { target: name })}>Withdraw</button>
          </div>
        ))}
        {(friendData.incoming_join || []).map((request) => <RequestRow key={`${request.room_id}-${request.requestor}`} title={request.requestor} subtitle={`wants to join ${request.title || request.room_id}`} accept={() => post("/api/rooms/respond-join", { room_id: request.room_id, requestor: request.requestor, accept: true })} ignore={() => post("/api/rooms/respond-join", { room_id: request.room_id, requestor: request.requestor, accept: false })} />)}
        {(friendData.incoming_invite || []).map((invite) => <RequestRow key={`${invite.room_id}-${invite.inviter}`} title={invite.title || invite.room_id} subtitle={`${invite.inviter} invited you`} accept={() => post("/api/rooms/respond-invite", { room_id: invite.room_id, inviter: invite.inviter, accept: true })} ignore={() => post("/api/rooms/respond-invite", { room_id: invite.room_id, inviter: invite.inviter, accept: false })} />)}
      </section>
      <section className="info-section">
        <h3>Friends</h3>
        {friends.map((friend) => (
          <div className="user-chip" key={friend}>
            <span className="avatar">{initials(friend)}</span><strong>{friend}</strong>
            {activeRoom?.is_group && !activeRoom.members.includes(friend) ? <button onClick={() => post("/api/rooms/add-member", { room_id: activeRoom.room_id, target: friend })}>Add</button> : null}
            <button onClick={() => post("/api/rooms/direct", { target: friend })}>Chat</button>
            <button className="secondary-btn" onClick={() => post("/api/friends/remove", { target: friend })}>Unfriend</button>
          </div>
        ))}
      </section>
      <section className="info-section">
        <h3>Online Now</h3>
        {onlineUsers.map((user) => <div className="user-chip" key={user}><span className="dot"></span><strong>{user}</strong></div>)}
      </section>
      <section className="info-section danger-section"><button className="danger-button" onClick={deleteAccount}>Delete Account</button></section>
    </aside>
  );
}

function RequestRow({ title, subtitle, accept, ignore }) {
  return (
    <div className="user-chip request-incoming">
      <strong>{title}</strong>
      {subtitle ? <small>{subtitle}</small> : null}
      <button onClick={accept}>Accept</button>
      <button className="secondary-btn" onClick={ignore}>Ignore</button>
    </div>
  );
}

function RoomInfo({ room, friends, friendData, addMembersOpen, setAddMembersOpen, post, close, deleteGroup, addSystem }) {
  const pending = new Set((friendData.outgoing_invite || []).filter((invite) => invite.room_id === room.room_id).map((invite) => invite.target));
  const addable = friends.filter((friend) => !room.members.includes(friend));
  return (
    <aside className="info-panel">
      <div className="info-head"><button className="icon-button" onClick={close}>Close</button><h3>{room.is_group ? "Group Info" : "Contact Info"}</h3></div>
      <div className="info-profile"><span className="avatar large">{initials(room.title)}</span><strong>{room.title}</strong><span>{room.is_group ? `${room.members.length} members` : "Direct chat"}</span></div>
      {room.is_group ? <section className="info-section"><h3>Description</h3><p>{room.description || "No description"}</p></section> : null}
      {room.is_group ? <section className="info-section"><button className="wide-action" onClick={() => copyGroupLink(room.room_id, addSystem)}>Copy Group Link</button></section> : null}
      <section className="info-section"><h3>Members</h3>{room.members.map((member) => <div className="user-chip" key={member}><span className="avatar">{initials(member)}</span><strong>{member}</strong></div>)}</section>
      {room.is_group ? (
        <section className="info-section">
          <button className="wide-action" onClick={() => setAddMembersOpen(!addMembersOpen)}>{addMembersOpen ? "Hide Add Members" : "Add Members"}</button>
          {addMembersOpen && addable.map((friend) => <div className="user-chip" key={friend}><strong>{friend}</strong><button disabled={pending.has(friend)} onClick={() => post("/api/rooms/add-member", { room_id: room.room_id, target: friend })}>{pending.has(friend) ? "Pending" : "Add"}</button></div>)}
        </section>
      ) : null}
      {room.is_owner ? <section className="info-section danger-section"><button className="danger-button" onClick={deleteGroup}>Delete Group</button></section> : null}
    </aside>
  );
}

function Message({ item, username }) {
  const mine = item.sender === username;
  if (item.kind === "system") return <article className="message system">{item.text}</article>;
  if (item.type === "file" || item.kind === "file" || item.kind === "voice") {
    if (item.kind === "voice") {
      return (
        <article className={`message ${mine ? "mine" : ""}`}>
          <div className="meta"><strong>{mine ? "You" : item.sender}</strong><span>{item.time}</span></div>
          <audio controls preload="metadata" src={item.url}></audio>
        </article>
      );
    }
    if (isImageFile(item.filename)) {
      return (
        <article className={`message ${mine ? "mine" : ""}`}>
          <div className="meta"><strong>{mine ? "You" : item.sender}</strong><span>{item.time}</span></div>
          <a className="image-message" href={item.url} target="_blank" rel="noreferrer">
            <img src={item.url} alt={item.filename} loading="lazy" />
          </a>
          <div className="file-caption">{item.filename} ({formatBytes(item.size || 0)})</div>
        </article>
      );
    }
    return (
      <article className={`message ${mine ? "mine" : ""}`}>
        <div className="meta"><strong>{mine ? "You" : item.sender}</strong><span>{item.time}</span></div>
        <a className="file-link" href={item.url} target="_blank" rel="noreferrer">{item.filename}</a>
      </article>
    );
  }
  return (
    <article className={`message ${mine ? "mine" : ""}`}>
      <div className="meta"><strong>{mine ? "You" : item.sender}</strong><span>{item.time}</span></div>
      <div>{item.text}</div>
    </article>
  );
}

function normalizeHistoryMessage(item) {
  if (item.type === "file") {
    return {
      ...item,
      id: item.id || `${item.time}-${item.filename}`,
      kind: item.kind || "file"
    };
  }
  return {
    id: item.id,
    sender: item.sender,
    text: item.message,
    time: item.time,
    kind: "chat"
  };
}

function preview(room, username) {
  if (!room.last_message) return room.is_group ? "No group messages yet" : "No messages yet";
  const prefix = room.last_message_sender === username ? "You: " : room.last_message_sender ? `${room.last_message_sender}: ` : "";
  return `${prefix}${room.last_message}`;
}

function isImageFile(filename) {
  return /\.(apng|avif|bmp|gif|jpe?g|png|webp)$/i.test(String(filename || ""));
}

function formatBytes(bytes) {
  const size = Number(bytes || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function seenKey(username) {
  return `chatshareSeen:${username || "guest"}`;
}

function loadSeen(username) {
  try {
    return JSON.parse(localStorage.getItem(seenKey(username)) || "{}");
  } catch (_error) {
    return {};
  }
}

function getJoinIdFromUrl() {
  return new URLSearchParams(window.location.search).get("join") || "";
}

function clearJoinParam() {
  const url = new URL(window.location.href);
  url.searchParams.delete("join");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

async function copyGroupLink(roomId, addSystem) {
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  url.searchParams.set("join", roomId);
  const link = url.toString();
  try {
    await navigator.clipboard.writeText(link);
    addSystem("Group link copied.");
  } catch (_error) {
    window.prompt("Copy group link", link);
  }
}

createRoot(document.getElementById("root")).render(<App />);
