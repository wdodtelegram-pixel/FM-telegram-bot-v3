import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/ui";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Scheduled from "./pages/Scheduled";
import Defects from "./pages/Defects";
import Access from "./pages/Access";
import EquipmentTypes from "./pages/EquipmentTypes";

export default function App() {
  const [user, setUser] = useState(() => {
    try { return localStorage.getItem("token") ? JSON.parse(localStorage.getItem("user")) : null; }
    catch { return null; }
  });

  useEffect(() => {
    const expired = () => setUser(null);
    window.addEventListener("auth:expired", expired);
    return () => window.removeEventListener("auth:expired", expired);
  }, []);

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    setUser(null);
  };

  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={user ? <Navigate to="/dashboard" replace /> : <Login onLogin={setUser} />} />
          {user ? (
            <Route element={<Layout user={user} onLogout={logout} />}>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/scheduled" element={<Scheduled />} />
              <Route path="/defects" element={<Defects />} />
              <Route path="/access" element={<Access />} />
              <Route path="/equipment" element={<EquipmentTypes />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
          ) : (
            <Route path="*" element={<Navigate to="/login" replace />} />
          )}
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  );
}
