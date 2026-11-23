import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { X } from "lucide-react";

const variants = {
  primary: "bg-gray-900 text-white hover:bg-gray-800 shadow-sm",
  secondary: "bg-gray-100 text-gray-900 border border-gray-300 hover:bg-gray-200",
  outline: "bg-white text-gray-900 border-2 border-gray-800 hover:bg-gray-50",
  danger: "bg-red-600 text-white hover:bg-red-700 shadow-sm",
  danger_outline: "bg-white text-red-700 border-2 border-red-600 hover:bg-red-50",
  success: "bg-green-600 text-white hover:bg-green-700 shadow-sm",
  ghost: "bg-transparent text-gray-700 hover:bg-gray-100",
};
const sizes = { xs: "px-2.5 py-1 text-xs", sm: "px-3 py-1.5 text-sm", md: "px-4 py-2 text-base" };

export function Button({ variant = "primary", size = "md", className = "", type = "button", ...props }) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-2 font-medium rounded-md transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    />
  );
}

const badge = {
  default: "bg-white text-gray-700 border border-gray-300",
  open: "bg-red-50 text-red-800 border border-red-200",
  reviewed: "bg-purple-50 text-purple-800 border border-purple-200",
  ongoing: "bg-yellow-50 text-yellow-800 border border-yellow-200",
  done: "bg-green-50 text-green-800 border border-green-200",
  completed: "bg-white text-gray-700 border border-gray-300",
  "yet to start": "bg-white text-gray-700 border border-gray-300",
  "in progress": "bg-yellow-50 text-yellow-800 border border-yellow-200",
  high: "bg-red-50 text-red-800 border border-red-200",
  medium: "bg-yellow-50 text-yellow-800 border border-yellow-200",
  low: "bg-blue-50 text-blue-800 border border-blue-200",
  scheduled: "bg-blue-50 text-blue-800 border border-blue-200",
  unscheduled: "bg-orange-50 text-orange-800 border border-orange-200",
  approved: "bg-green-50 text-green-800 border border-green-200",
  pending: "bg-yellow-50 text-yellow-800 border border-yellow-200",
  denied: "bg-red-50 text-red-800 border border-red-200",
  revoked: "bg-gray-100 text-gray-700 border border-gray-300",
  master_control: "bg-gray-900 text-white border border-gray-900",
  end_user: "bg-white text-gray-700 border border-gray-300",
};

export function Badge({ children, variant }) {
  const key = String(variant ?? children).toLowerCase();
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${badge[key] || badge.default}`}>
      {children}
    </span>
  );
}

export function Card({ title, children, className = "", actions }) {
  return (
    <section className={`bg-white border-2 border-gray-300 rounded-lg ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const field = "w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600";

export function Input({ label, className = "", ...props }) {
  return (
    <label className="block text-sm text-gray-700">
      {label && <span className="block mb-1 font-medium">{label}</span>}
      <input className={`${field} ${className}`} {...props} />
    </label>
  );
}

export function Select({ label, children, className = "", ...props }) {
  return (
    <label className="block text-sm text-gray-700">
      {label && <span className="block mb-1 font-medium">{label}</span>}
      <select className={`${field} ${className}`} {...props}>{children}</select>
    </label>
  );
}

export function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className={`bg-white rounded-lg shadow-xl w-full ${wide ? "max-w-3xl" : "max-w-lg"} mt-12`}>
        <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900">{title}</h2>
          <button aria-label="Close" onClick={onClose} className="p-1 rounded hover:bg-gray-100"><X size={18} /></button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function Pagination({ page, pages, total, onPage }) {
  return (
    <div className="flex items-center justify-between gap-3 pt-3 text-sm text-gray-600">
      <span>{total} result{total === 1 ? "" : "s"}</span>
      <div className="flex items-center gap-2">
        <Button size="xs" variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <span>Page {page} of {pages}</span>
        <Button size="xs" variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

export const Spinner = () => <div className="py-8 text-center text-sm text-gray-500">Loading…</div>;

export const ErrorBox = ({ children }) =>
  children ? <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{children}</div> : null;

const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null);
  const show = useCallback((message, tone = "ok") => {
    setToast({ message, tone });
    setTimeout(() => setToast(null), 3500);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && (
        <div role="status" className={`fixed bottom-4 right-4 z-[60] rounded-md px-4 py-3 text-sm shadow-lg ${toast.tone === "error" ? "bg-red-600 text-white" : "bg-gray-900 text-white"}`}>
          {toast.message}
        </div>
      )}
    </ToastCtx.Provider>
  );
}

export const Table = ({ children }) => (
  <div className="overflow-x-auto"><table className="min-w-full text-sm">{children}</table></div>
);
export const Th = ({ children }) => <th className="text-left font-medium text-gray-600 px-3 py-2 border-b border-gray-300 whitespace-nowrap">{children}</th>;
export const Td = ({ children, className = "" }) => <td className={`px-3 py-2 border-b border-gray-100 align-top ${className}`}>{children}</td>;
