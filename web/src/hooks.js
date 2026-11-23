import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "./services/api";

/** GET `path` with `params`; reload() refetches. Re-runs when params change. */
export function useApi(path, params = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const key = JSON.stringify(params);

  const load = useCallback(() => {
    setLoading(true);
    return api
      .get(path, { params: JSON.parse(key) })
      .then((r) => { setData(r.data); setError(""); })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, [path, key]);

  useEffect(() => { load(); }, [load]);
  return { data, error, loading, reload: load };
}

export const fmt = {
  when(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    const date = d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
    const hasTime = d.getHours() || d.getMinutes();
    return hasTime ? `${date} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : date;
  },
  span(item) {
    const s = item.starts_at, e = item.ends_at;
    if (s && e) {
      const same = s.slice(0, 10) === e.slice(0, 10);
      return same ? `${fmt.when(s)} – ${e.slice(11, 16)}` : `${fmt.when(s)} → ${fmt.when(e)}`;
    }
    if (s || e) return fmt.when(s || e);
    const due = item.next_job_date || item.estimated_completion;
    return due ? fmt.when(due) : "no date";
  },
};
