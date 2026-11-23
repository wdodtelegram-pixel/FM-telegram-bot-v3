import { Link } from "react-router-dom";
import { Card, ErrorBox, Spinner, Table, Td, Th } from "../components/ui";
import { useApi } from "../hooks";

const Stat = ({ label, value, to, tone = "" }) => (
  <Link to={to} className="block rounded-md border border-gray-200 bg-gray-50 p-3 hover:bg-gray-100">
    <div className={`text-2xl font-bold ${tone}`}>{value}</div>
    <div className="text-xs text-gray-600">{label}</div>
  </Link>
);

export default function Dashboard() {
  const { data, error, loading } = useApi("/dashboard");
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox>{error}</ErrorBox>;
  const { scheduled: s, reports: r, access: a } = data;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Scheduled items & events">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Total" value={s.total} to="/scheduled" />
            <Stat label="Today" value={s.today} to="/scheduled" />
            <Stat label="Next 7 days" value={s.next_7_days} to="/scheduled" />
            <Stat label="Overdue" value={s.overdue} to="/scheduled" tone={s.overdue ? "text-red-700" : ""} />
          </div>
        </Card>
        <Card title="Defect reports">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Open" value={r.open} to="/defects" />
            <Stat label="Last 7 days" value={r.last_7_days} to="/defects" />
            <Stat label="Matched a scheduled item" value={r.scheduled} to="/defects" />
            <Stat label="Unscheduled" value={r.unscheduled} to="/defects" />
          </div>
          <p className="mt-3 text-xs text-gray-600">{r.added_to_existing} report(s) were added to an earlier report instead of creating a duplicate.</p>
        </Card>
        <Card title="Access">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Waiting for approval" value={a.pending} to="/access" tone={a.pending ? "text-red-700" : ""} />
            <Stat label="Approved" value={a.approved} to="/access" />
            <Stat label="Master control" value={a.master_control} to="/access" />
            <Stat label="Denied / revoked" value={a.denied + a.revoked} to="/access" />
          </div>
        </Card>
      </div>

      <Card title="By equipment type">
        <Table>
          <thead><tr><Th>Type</Th><Th>Scheduled</Th><Th>Still open</Th><Th>Defect reports</Th></tr></thead>
          <tbody>
            {s.by_type.map((t) => (
              <tr key={t.key}>
                <Td>{t.emoji} {t.name}</Td><Td>{t.scheduled_total}</Td><Td>{t.scheduled_open}</Td><Td>{t.reports}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
