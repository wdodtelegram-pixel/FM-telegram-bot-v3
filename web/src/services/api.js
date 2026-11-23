import axios from "axios";

// One origin: /api is proxied by Vite in development and by nginx in Docker.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// A 401 anywhere means the session is gone: drop it and let the app show the login.
api.interceptors.response.use(
  (r) => r,
  (error) => {
    const url = error.config?.url || "";
    if (error.response?.status === 401 && !url.includes("/auth/login")) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      window.dispatchEvent(new Event("auth:expired"));
    }
    return Promise.reject(error);
  },
);

export const errorMessage = (error) =>
  error?.response?.data?.error || error?.message || "Something went wrong.";

export default api;
