export type Row = Record<string, any>;

let token: string | null = localStorage.getItem("erp_token");
export const getToken = () => token;
export function setToken(t: string | null) {
  token = t;
  if (t) localStorage.setItem("erp_token", t);
  else localStorage.removeItem("erp_token");
}

let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (f: () => void) => (onUnauthorized = f);

export class ApiErr extends Error {}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; params?: Row } = {}): Promise<T> {
  let url = "/api" + path;
  if (opts.params) {
    const q = new URLSearchParams();
    Object.entries(opts.params).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && q.set(k, String(v)));
    const s = q.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = "Bearer " + token;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  } catch {
    throw new ApiErr("Cannot reach the local server. Is the ERP service running?");
  }
  if (res.status === 401 && token) onUnauthorized();
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new ApiErr(msg);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export async function download(path: string, filename: string, params?: Row) {
  let url = "/api" + path;
  if (params) url += "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString();
  const res = await fetch(url, { headers: token ? { Authorization: "Bearer " + token } : {} });
  if (!res.ok) throw new ApiErr("Download failed");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- formatting & money helpers (all amounts are integer paise) ----------
export const inr = (p: number | null | undefined) =>
  "₹" + ((p || 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const toPaise = (s: string | number) => Math.round(parseFloat(String(s || "0")) * 100) || 0;
export const rupees = (p: number) => (p / 100).toFixed(2);
export const fdate = (s: string) => (s ? new Date(s).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "");
export const fdt = (s: string) => (s ? new Date(s).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
export const num = (n: number) => String(Math.round(n * 1000) / 1000);

// preview of server tax maths
export function calcLine(qty: number, price: number, discount: number, rate: number, inclusive: boolean) {
  const gross = Math.round(qty * price) - discount;
  const taxable = inclusive ? Math.round((gross * 100) / (100 + rate)) : gross;
  const tax = inclusive ? gross - taxable : Math.round((gross * rate) / 100);
  return { taxable, tax, total: taxable + tax };
}

export const ROLES = ["owner", "manager", "cashier", "stock", "accountant"];
