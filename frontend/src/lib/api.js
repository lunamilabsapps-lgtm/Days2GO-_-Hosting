import axios from "axios";

export const BACKEND = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND}/api`;

export const getToken = () => localStorage.getItem("bc_token");
export const setToken = (t) => (t ? localStorage.setItem("bc_token", t) : localStorage.removeItem("bc_token"));

export const api = axios.create({ baseURL: API });
api.interceptors.request.use((cfg) => {
  const t = getToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && !err.config.url.includes("/auth/login")) {
      setToken(null);
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export const errMsg = (e) => e?.response?.data?.detail || e?.message || "Something went wrong";
export const fmtDate = (s) => (s ? new Date(s).toLocaleString("en-AU", { dateStyle: "medium", timeStyle: "short" }) : "—");
export const fmtTime = (s) => (s ? new Date(s).toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");
export const label = (s) => (s ? String(s).replace(/_/g, " ") : "—");
export const shotUrl = (name) => (name ? `${API}/screenshots/${name}?token=${getToken()}` : null);
export const authUrl = (path) => `${API}${path}${path.includes("?") ? "&" : "?"}token=${getToken()}`;
