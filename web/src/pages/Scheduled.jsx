import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import api, { errorMessage } from "../services/api";
import { Badge, Button, Card, ErrorBox, Input, Modal, Pagination, Select, Spinner, Table, Td, Th, useToast } from "../components/ui";
import { fmt, useApi } from "../hooks";

function ImportModal({ onClose, onDone }) {
  const file = useRef(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const run = async (dry) => {
    const f = file.current?.files?.[0];
    if (!f) { setError("Choose a CSV file first."); return; }
    setBusy(true); setError("");
    const body = new FormData();
    body.append("file", f);
    if (dry) body.append("dry_run", "1");
    try {
      const { data } = await api.post("/scheduled/import", body, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(data);
      if (!dry) { toast(`Imported: ${data.created} created, ${data.updated} updated`); onDone(); }
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };

  return (
    <Modal title="Import scheduled items from CSV" onClose={onClose} wide>
      <div className="space-y-3">
        <p className="text-sm text-gray-600">
          Columns: <code>job_ref, category, description, location, starts_at, ends_at, maintenance_type, status, next_job_date, schedule_note</code>.
          <b> category</b>, <b>description</b> and <b>location</b> are required. Rows with an existing <code>job_ref</code> are updated.
        </p>
        <input ref={file} type="file" accept=".csv,text/csv" aria-label="CSV file" className="block text-sm" />
        <ErrorBox>{error}</ErrorBox>
        <div className="flex gap-2">
          <Button variant="outline" disabled={busy} onClick={() => run(true)}>Check first (saves nothing)</Button>
          <Button disabled={busy} onClick={() => run(false)}><Upload size={16} /> Import</Button>
        </div>
        {result && (
          <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm" aria-live="polite">
            <p className="font-medium">
              {result.dry_run ? "Check result (nothing saved): " : "Imported: "}
              {result.created} created, {result.updated} updated, {result.skipped.length} skipped
            </p>
            {result.skipped.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-red-800 max-h-48 overflow-y-auto">
                {result.skipped.map((s) => <li key={s.line}>Line {s.line}: {s.reason}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}

export default function Scheduled() {
  const [filters, setFilters] = useState({ type: "", status: "", q: "", from: "", to: "" });
  const [page, setPage] = useState(1);
  const [importing, setImporting] = useState(false);
  const types = useApi("/equipment-types");
  const params = { ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), page };
  const { data, error, loading, reload } = useApi("/scheduled", params);
  const set = (k) => (e) => { setFilters({ ...filters, [k]: e.target.value }); setPage(1); };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Scheduled items & events</h1>
        <Button onClick={() => setImporting(true)}><Upload size={16} /> Import CSV</Button>
      </div>
      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Select label="Equipment type" value={filters.type} onChange={set("type")}>
            <option value="">All</option>
            {types.data?.items.map((t) => <option key={t.key} value={t.key}>{t.emoji} {t.name}</option>)}
          </Select>
          <Select label="Status" value={filters.status} onChange={set("status")}>
            <option value="">All</option><option>Yet to Start</option><option>In Progress</option><option>Completed</option>
          </Select>
          <Input label="From" type="date" value={filters.from} onChange={set("from")} />
          <Input label="To" type="date" value={filters.to} onChange={set("to")} />
          <Input label="Search" placeholder="description, location, ref" value={filters.q} onChange={set("q")} />
        </div>
      </Card>
      <ErrorBox>{error}</ErrorBox>
      <Card>
        {loading && !data ? <Spinner /> : (
          <>
            <Table>
              <thead><tr><Th>Ref</Th><Th>Type</Th><Th>Description</Th><Th>Location</Th><Th>When</Th><Th>Status</Th></tr></thead>
              <tbody>
                {data?.items.map((j) => (
                  <tr key={j.id}>
                    <Td className="font-mono text-xs">{j.job_ref}</Td>
                    <Td>{j.type ? `${j.type.emoji || ""} ${j.type.name}` : j.category}</Td>
                    <Td>{j.description}</Td><Td>{j.location}</Td>
                    <Td className="whitespace-nowrap">{fmt.span(j)}</Td>
                    <Td><Badge>{j.status}</Badge></Td>
                  </tr>
                ))}
                {data?.items.length === 0 && <tr><Td className="text-gray-500" colSpan={6}>Nothing matches these filters.</Td></tr>}
              </tbody>
            </Table>
            {data && <Pagination page={data.page} pages={data.pages} total={data.total} onPage={setPage} />}
          </>
        )}
      </Card>
      {importing && <ImportModal onClose={() => setImporting(false)} onDone={reload} />}
    </div>
  );
}
