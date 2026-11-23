import { useState } from "react";
import { Check, RotateCcw, ShieldOff, Star, X } from "lucide-react";
import api, { errorMessage } from "../services/api";
import { Badge, Button, Card, ErrorBox, Modal, Select, Spinner, Table, Td, Th, useToast } from "../components/ui";
import { fmt, useApi } from "../hooks";

export default function Access() {
  const { data, error, loading, reload } = useApi("/access/members");
  const toast = useToast();
  const [confirm, setConfirm] = useState(null);       // {member, action}
  const [linking, setLinking] = useState(null);       // member
  const [webId, setWebId] = useState("");

  const act = async (member, action, body = {}) => {
    try {
      await api.post(`/access/members/${member.id}/${action}`, body);
      toast(`${member.name}: ${action === "approve" ? "approved" : action === "deny" ? "denied" : action === "revoke" ? "access removed" : "put back to pending"}. They will be told in Telegram.`);
      reload();
    } catch (e) { toast(errorMessage(e), "error"); }
  };
  const patch = async (member, body) => {
    try { await api.patch(`/access/members/${member.id}`, body); toast("Saved."); reload(); }
    catch (e) { toast(errorMessage(e), "error"); }
  };

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox>{error}</ErrorBox>;
  const members = data.items;
  const pending = members.filter((m) => m.status === "pending");
  const others = members.filter((m) => m.status !== "pending");

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Access</h1>
      <p className="text-sm text-gray-600">
        People ask once in Telegram. Approve them here or in the bot; the decision is remembered. End users use Telegram only;
        master control also signs in to this website.
      </p>

      <Card title={`Waiting for approval (${pending.length})`}>
        {pending.length === 0 ? <p className="text-sm text-gray-500">No pending requests.</p> : (
          <ul className="divide-y divide-gray-100">
            {pending.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div>
                  <div className="font-medium">{m.name}</div>
                  <div className="text-xs text-gray-500">{m.username ? `@${m.username} · ` : ""}Telegram ID {m.chat_id} · asked {fmt.when(m.requested_at)}</div>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="success" onClick={() => act(m, "approve", { tier: "end_user" })}><Check size={14} /> Approve</Button>
                  <Button size="sm" variant="outline" onClick={() => act(m, "approve", { tier: "master_control" })}><Star size={14} /> Approve as master</Button>
                  <Button size="sm" variant="danger_outline" onClick={() => act(m, "deny")}><X size={14} /> Deny</Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Everyone else">
        <Table>
          <thead><tr><Th>Name</Th><Th>Telegram</Th><Th>Tier</Th><Th>Status</Th><Th>Web account</Th><Th>Actions</Th></tr></thead>
          <tbody>
            {others.map((m) => (
              <tr key={m.id}>
                <Td>{m.name}</Td>
                <Td className="text-xs text-gray-600">{m.username ? `@${m.username}` : m.chat_id}</Td>
                <Td>
                  {m.status === "approved" ? (
                    <Select aria-label={`Tier for ${m.name}`} value={m.tier} onChange={(e) => patch(m, { tier: e.target.value })}>
                      <option value="end_user">End user</option><option value="master_control">Master control</option>
                    </Select>
                  ) : <Badge variant={m.tier}>{m.tier === "master_control" ? "Master control" : "End user"}</Badge>}
                </Td>
                <Td><Badge variant={m.status}>{m.status}</Badge></Td>
                <Td>
                  <button className="underline decoration-dotted text-sm" onClick={() => { setLinking(m); setWebId(m.user_id ?? ""); }}>
                    {m.user_id ? `#${m.user_id}` : "link"}
                  </button>
                </Td>
                <Td>
                  {m.status === "approved" && <Button size="xs" variant="danger_outline" onClick={() => setConfirm({ member: m, action: "revoke" })}><ShieldOff size={12} /> Revoke</Button>}
                  {(m.status === "denied" || m.status === "revoked") && <Button size="xs" variant="secondary" onClick={() => act(m, "reconsider")}><RotateCcw size={12} /> Reconsider</Button>}
                </Td>
              </tr>
            ))}
            {others.length === 0 && <tr><Td className="text-gray-500" colSpan={6}>Nobody yet.</Td></tr>}
          </tbody>
        </Table>
      </Card>

      {confirm && (
        <Modal title="Remove access?" onClose={() => setConfirm(null)}>
          <p className="text-sm mb-4">{confirm.member.name} will no longer be able to use the bot{confirm.member.tier === "master_control" ? " or this website" : ""}. They cannot ask again unless you reconsider them.</p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setConfirm(null)}>Keep access</Button>
            <Button variant="danger" onClick={() => { act(confirm.member, "revoke"); setConfirm(null); }}>Revoke</Button>
          </div>
        </Modal>
      )}
      {linking && (
        <Modal title={`Web account for ${linking.name}`} onClose={() => setLinking(null)}>
          <p className="text-sm text-gray-600 mb-3">Links this person to a row in the web app's users table (needed for website login and for "assigned to me" in the bot). Leave empty to unlink.</p>
          <input aria-label="Web user id" type="number" min="1" className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" value={webId} onChange={(e) => setWebId(e.target.value)} />
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="secondary" onClick={() => setLinking(null)}>Cancel</Button>
            <Button onClick={() => { patch(linking, { user_id: webId === "" ? null : Number(webId) }); setLinking(null); }}>Save</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
