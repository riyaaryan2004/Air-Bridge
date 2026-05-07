export async function api(path, options = {}) {
  const token = localStorage.getItem("chatshareToken");
  const headers = {
    ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(token ? { "X-Auth-Token": token } : {}),
    ...(options.headers || {})
  };
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    return { ok: false, error: data.error || response.statusText || "Request failed" };
  }
  return data;
}
