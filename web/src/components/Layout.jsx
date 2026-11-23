import { NavLink, Outlet } from "react-router-dom";
import { CalendarClock, Gauge, LogOut, ShieldCheck, TriangleAlert, Wrench } from "lucide-react";
import { Button } from "./ui";
import { useApi } from "../hooks";

const items = [
  { to: "/dashboard", label: "Dashboard", icon: Gauge },
  { to: "/scheduled", label: "Scheduled & events", icon: CalendarClock },
  { to: "/defects", label: "Defect reports", icon: TriangleAlert },
  { to: "/access", label: "Access", icon: ShieldCheck, badge: true },
  { to: "/equipment", label: "Equipment types", icon: Wrench },
];

export default function Layout({ user, onLogout }) {
  const { data } = useApi("/dashboard");
  const pending = data?.access?.pending || 0;

  return (
    <div className="min-h-screen wf-app">
      <a href="#main-content" className="skip-to-content">Skip to main content</a>
      <header className="fixed top-0 inset-x-0 z-40 h-16 bg-white border-b-2 border-gray-300 flex items-center justify-between px-4">
        <div className="font-bold text-gray-900">FM Control</div>
        <div className="flex items-center gap-3 text-sm">
          <span className="hidden sm:inline text-gray-600">{user?.name}</span>
          <Button size="sm" variant="outline" onClick={onLogout}><LogOut size={16} /> Sign out</Button>
        </div>
      </header>

      <aside className="fixed left-0 top-16 bottom-0 w-60 bg-white border-r-2 border-gray-300 overflow-y-auto hidden md:block">
        <nav className="p-3 flex flex-col gap-1" aria-label="Main">
          {items.map(({ to, label, icon: Icon, badge }) => (
            <NavLink key={to} to={to}
              className={({ isActive }) => `flex items-center gap-3 px-3 py-2 rounded-md border transition-colors ${isActive ? "bg-gray-900 text-white border-gray-900" : "border-transparent text-gray-700 hover:bg-gray-100"}`}>
              <Icon size={18} /> <span className="flex-1">{label}</span>
              {badge && pending > 0 && <span className="rounded-full bg-red-600 text-white text-xs px-2 py-0.5">{pending}</span>}
            </NavLink>
          ))}
        </nav>
      </aside>

      <nav className="md:hidden fixed top-16 inset-x-0 z-30 bg-white border-b border-gray-300 flex overflow-x-auto" aria-label="Main (mobile)">
        {items.map(({ to, label }) => (
          <NavLink key={to} to={to} className={({ isActive }) => `px-3 py-2 text-sm whitespace-nowrap ${isActive ? "font-semibold border-b-2 border-gray-900" : "text-gray-600"}`}>{label}</NavLink>
        ))}
      </nav>

      <main id="main-content" tabIndex="-1" className="pt-16 md:pl-60">
        <div className="p-4 sm:p-6 lg:p-8 pt-14 md:pt-6"><Outlet /></div>
      </main>
    </div>
  );
}
