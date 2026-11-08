// API client: JSON over fetch with CSRF token, consistent errors, and session-expiry signalling.
let csrf = "";
export const setCsrf = (t) => { csrf = t || ""; };
export const events = new EventTarget();

export class ApiError extends Error {
  constructor(status, message, code, fields) {
    super(message);
    this.status = status; this.code = code || null; this.fields = fields || {};
  }
}

function qs(params) {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "" || v === false) continue;
    u.set(k, v === true ? "1" : String(v));
  }
  const s = u.toString();
  return s ? "?" + s : "";
}
export const withQuery = (url, params) => url + qs(params);

export async function request(method, url, { body, params, form, signal } = {}) {
  const headers = { Accept: "application/json" };
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  if (method !== "GET") headers["X-CSRF-Token"] = csrf;
  let res;
  try {
    res = await fetch(url + qs(params), { method, headers, body: payload, credentials: "same-origin", signal });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError(0, "Cannot reach the server. Check your internet connection and try again.", "network");
  }
  const type = res.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const e = data.error || {};
      const err = new ApiError(res.status, e.message || "Something went wrong.", e.code, e.fields);
      if (res.status === 401 && url !== "/api/auth/login" && url !== "/api/auth/me") events.dispatchEvent(new CustomEvent("auth", { detail: err }));
      if (err.code === "password_change_required") events.dispatchEvent(new CustomEvent("password", { detail: err }));
      if (err.code === "csrf") events.dispatchEvent(new CustomEvent("csrf", { detail: err }));
      throw err;
    }
    return data;
  }
  if (!res.ok) throw new ApiError(res.status, "Something went wrong (" + res.status + ").");
  return res; // binary (PDF, backups)
}

export const get = (url, params, opts) => request("GET", url, { params, ...opts });
export const post = (url, body) => request("POST", url, { body: body ?? {} });
export const put = (url, body) => request("PUT", url, { body: body ?? {} });
export const del = (url, body) => request("DELETE", url, { body: body ?? {} });
export const upload = (url, form, method = "POST") => request(method, url, { form });

/** Download a binary response (PDF) with the session cookie. */
export async function download(url, params, fallbackName) {
  const res = await request("GET", url, { params });
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename="?([^";]+)"?/.exec(cd);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : fallbackName || "download";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
