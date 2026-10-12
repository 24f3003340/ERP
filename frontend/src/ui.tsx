import React, { createContext, useCallback, useContext, useState } from "react";
import { Row } from "./api";

// ---------- toasts ----------
type Toast = { id: number; msg: string; kind: "ok" | "err" };
const ToastCtx = createContext<(msg: string, kind?: "ok" | "err") => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((msg: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((s) => [...s, { id, msg, kind }]);
    setTimeout(() => setItems((s) => s.filter((x) => x.id !== id)), kind === "err" ? 6000 : 3000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (<div key={t.id} className={"toast " + t.kind}>{t.msg}</div>))}
      </div>
    </ToastCtx.Provider>
  );
}

// ---------- auth context ----------
export type Session = { user: Row; business: Row; refresh: () => Promise<void>; can: (p: string) => boolean };
export const SessionCtx = createContext<Session>(null as any);
export const useSession = () => useContext(SessionCtx);

// ---------- small components ----------
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={"modal" + (wide ? " wide" : "")} role="dialog" aria-label={title}>
        <div className="modal-head"><h3>{title}</h3><button className="btn ghost" onClick={onClose} aria-label="Close">✕</button></div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (<label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>);
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Loading() { return <div className="empty">Loading…</div>; }

export function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (<div className={"stat " + (tone || "")}><div className="stat-label">{label}</div><div className="stat-value">{value}</div></div>);
}

export function Badge({ children, tone }: { children: React.ReactNode; tone?: "ok" | "warn" | "err" | "muted" }) {
  return <span className={"badge " + (tone || "muted")}>{children}</span>;
}

export function Table({ head, children, className }: { head: string[]; children: React.ReactNode; className?: string }) {
  return (
    <div className="table-wrap"><table className={className}>
      <thead><tr>{head.map((h, i) => (<th key={i}>{h}</th>))}</tr></thead>
      <tbody>{children}</tbody>
    </table></div>
  );
}

export function useAsync<T>(fn: () => Promise<T>, deps: any[]): { data: T | null; error: string; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    fn().then((d) => { if (alive) { setData(d); setError(""); } })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((x) => x + 1) };
}
