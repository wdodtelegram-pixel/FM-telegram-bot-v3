import { useState } from "react";
import api, { errorMessage } from "../services/api";
import { Button, ErrorBox, Input } from "../components/ui";

export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const { data } = await api.post("/auth/login", { email, password });
      localStorage.setItem("token", data.token);
      localStorage.setItem("user", JSON.stringify(data.user));
      onLogin(data.user);
    } catch (err) {
      setError(errorMessage(err));
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen wf-app flex items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white border-2 border-gray-300 rounded-lg p-6 space-y-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">FM Control</h1>
          <p className="text-sm text-gray-600">Master control sign-in</p>
        </div>
        <ErrorBox>{error}</ErrorBox>
        <Input label="Email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Input label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Button type="submit" className="w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
        <p className="text-xs text-gray-500">End users use the Telegram bot; the website is for master control.</p>
      </form>
    </div>
  );
}
