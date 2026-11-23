import { useState } from "react";
import { Camera } from "lucide-react";
import { Badge, Card, ErrorBox, Input, Modal, Pagination, Select, Spinner, Table, Td, Th } from "../components/ui";
import { fmt, useApi } from "../hooks";

function Detail({ id, onClose }) {
  const { data, error, loading } = useApi(`/defects/${id}`);
  return (
    <Modal title={data ? `Report #${data.id}` : "Report"} onClose={onClose} wide>
      {loading && !data ? <Spinner /> : error ? <ErrorBox>{error}</ErrorBox> : (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap gap-2">
            <Badge variant={data.kind}>{data.kind}</Badge><Badge variant={data.status}>{data.status}</Badge>
            <Badge variant={data.priority}>{data.priority}</Badge>
            {data.has_image && <span className="inline-flex items-center gap-1 text-gray-600"><Camera size={14} /> photo attached (view in Telegram/BMS)</span>}
          </div>
          <h3 className="text-base font-semibold">{data.title}</h3>
          <p className="whitespace-pre-wrap">{data.description}</p>
          <dl className="grid grid-cols-[8rem_1fr] gap-y-1">
            <dt className="text-gray-500">Equipment type</dt><dd>{data.type ? `${data.type.emoji || ""} ${data.type.name}` : "—"}</dd>
            <dt className="text-gray-500">Location</dt><dd>{data.location || data.building || "—"}</dd>
            <dt className="text-gray-500">Equipment</dt><dd>{data.specific_equipment || "—"}</dd>
            <dt className="text-gray-500">Occurred</dt><dd>{fmt.when(data.occurred_at)}</dd>
            <dt className="text-gray-500">Reported by</dt><dd>{data.reporter || "—"}{data.reported_via_bot && " (Telegram)"}</dd>
            {data.scheduled_job && (<><dt className="text-gray-500">Scheduled item</dt><dd>{data.scheduled_job.job_ref}: {data.scheduled_job.description}</dd></>)}
          </dl>
          {data.merged_reports.length > 0 && (
            <div>
              <h4 className="font-semibold mb-1">Added to this report ({data.merged_reports.length})</h4>
              <ul className="space-y-1">
                {data.merged_reports.map((m) => (
                  <li key={m.id} className="rounded border border-gray-200 bg-gray-50 px-3 py-2">
                    {m.description} <span className="text-gray-500">— {m.reporter}, {fmt.when(m.occurred_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.comments.length > 0 && (
            <div>
              <h4 className="font-semibold mb-1">History</h4>
              <ul className="space-y-1">{data.comments.map((c) => <li key={c.id} className="text-gray-700">• {c.text}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

export default function Defects() {
  const [filters, setFilters] = useState({ kind: "", type: "", status: "", q: "" });
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(null);
  const types = useApi("/equipment-types");
  const params = { ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), page };
  const { data, error, loading } = useApi("/defects", params);
  const set = (k) => (e) => { setFilters({ ...filters, [k]: e.target.value }); setPage(1); };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Defect reports</h1>
      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Select label="Kind" value={filters.kind} onChange={set("kind")}>
            <option value="">All</option><option value="scheduled">Scheduled</option><option value="unscheduled">Unscheduled</option>
          </Select>
          <Select label="Equipment type" value={filters.type} onChange={set("type")}>
            <option value="">All</option>
            {types.data?.items.map((t) => <option key={t.key} value={t.key}>{t.emoji} {t.name}</option>)}
          </Select>
          <Select label="Status" value={filters.status} onChange={set("status")}>
            <option value="">All</option><option>Open</option><option>Reviewed</option><option>Ongoing</option><option>Done</option><option>Completed</option>
          </Select>
          <Input label="Search" placeholder="issue, location, equipment" value={filters.q} onChange={set("q")} />
        </div>
      </Card>
      <ErrorBox>{error}</ErrorBox>
      <Card>
        {loading && !data ? <Spinner /> : (
          <>
            <Table>
              <thead><tr><Th>#</Th><Th>Issue</Th><Th>Type</Th><Th>Location</Th><Th>Kind</Th><Th>Occurred</Th><Th>Reporter</Th><Th>Added</Th></tr></thead>
              <tbody>
                {data?.items.map((d) => (
                  <tr key={d.id} className="cursor-pointer hover:bg-gray-50" onClick={() => setOpen(d.id)}>
                    <Td>{d.id}</Td>
                    <Td><button className="text-left underline decoration-dotted" onClick={() => setOpen(d.id)}>{d.title}</button></Td>
                    <Td>{d.type ? `${d.type.emoji || ""} ${d.type.name}` : "—"}</Td>
                    <Td>{d.location || d.building || "—"}</Td>
                    <Td><Badge variant={d.kind}>{d.kind}</Badge></Td>
                    <Td className="whitespace-nowrap">{fmt.when(d.occurred_at)}</Td>
                    <Td>{d.reporter || "—"}</Td>
                    <Td>{d.merged_count > 0 ? `+${d.merged_count}` : ""}</Td>
                  </tr>
                ))}
                {data?.items.length === 0 && <tr><Td className="text-gray-500" colSpan={8}>No reports match these filters.</Td></tr>}
              </tbody>
            </Table>
            {data && <Pagination page={data.page} pages={data.pages} total={data.total} onPage={setPage} />}
          </>
        )}
      </Card>
      {open && <Detail id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
