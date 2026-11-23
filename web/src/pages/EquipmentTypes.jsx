import { useState } from "react";
import { Plus } from "lucide-react";
import api, { errorMessage } from "../services/api";
import { Badge, Button, Card, ErrorBox, Input, Modal, Spinner, Table, Td, Th, useToast } from "../components/ui";
import { useApi } from "../hooks";

function Editor({ item, onClose, onSaved }) {
  const isNew = !item;
  const [form, setForm] = useState({ key: "", name: item?.name || "", emoji: item?.emoji || "", blurb: item?.blurb || "" });
  const [error, setError] = useState("");
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const save = async (e) => {
    e.preventDefault(); setError("");
    try {
      if (isNew) await api.post("/equipment-types", form);
      else await api.patch(`/equipment-types/${item.id}`, { name: form.name, emoji: form.emoji, blurb: form.blurb });
      onSaved();
    } catch (err) { setError(errorMessage(err)); }
  };

  return (
    <Modal title={isNew ? "Add equipment type" : `Edit ${item.name}`} onClose={onClose}>
      <form onSubmit={save} className="space-y-3">
        <ErrorBox>{error}</ErrorBox>
        {isNew && <Input label="Key (short, lowercase, used in commands)" placeholder="crane" required value={form.key} onChange={set("key")} />}
        <Input label="Name" placeholder="Tower Crane" required value={form.name} onChange={set("name")} />
        <Input label="Emoji" placeholder="🏗" value={form.emoji} onChange={set("emoji")} />
        <Input label="Short description" placeholder="Crane servicing" value={form.blurb} onChange={set("blurb")} />
        {!isNew && <p className="text-xs text-gray-500">Renaming updates every scheduled item of this type.</p>}
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit">Save</Button></div>
      </form>
    </Modal>
  );
}

export default function EquipmentTypes() {
  const { data, error, loading, reload } = useApi("/equipment-types");
  const [editing, setEditing] = useState(undefined);       // undefined closed, null new, object edit
  const toast = useToast();

  const toggle = async (t) => {
    try { await api.patch(`/equipment-types/${t.id}`, { active: !t.active }); reload(); }
    catch (e) { toast(errorMessage(e), "error"); }
  };

  if (loading && !data) return <Spinner />;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Equipment types</h1>
        <Button onClick={() => setEditing(null)}><Plus size={16} /> Add type</Button>
      </div>
      <p className="text-sm text-gray-600">These are the categories the bot offers when someone reports a defect or queries events. "Event" is a category like any other. Changes reach the bot within a minute.</p>
      <ErrorBox>{error}</ErrorBox>
      <Card>
        <Table>
          <thead><tr><Th></Th><Th>Name</Th><Th>Key</Th><Th>Description</Th><Th>Status</Th><Th>Actions</Th></tr></thead>
          <tbody>
            {data?.items.map((t) => (
              <tr key={t.id}>
                <Td className="text-xl">{t.emoji}</Td><Td>{t.name}</Td><Td className="font-mono text-xs">{t.key}</Td><Td>{t.blurb}</Td>
                <Td><Badge variant={t.active ? "approved" : "revoked"}>{t.active ? "active" : "disabled"}</Badge></Td>
                <Td><div className="flex gap-2">
                  <Button size="xs" variant="secondary" onClick={() => setEditing(t)}>Edit</Button>
                  <Button size="xs" variant="outline" onClick={() => toggle(t)}>{t.active ? "Disable" : "Enable"}</Button>
                </div></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      {editing !== undefined && <Editor item={editing} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); toast("Saved."); reload(); }} />}
    </div>
  );
}
