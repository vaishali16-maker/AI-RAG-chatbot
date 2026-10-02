"use client";

import { useEffect, useState } from "react";
import { RequireAuth } from "@/lib/require-auth";
import { useAuth } from "@/lib/auth-context";
import { Sidebar } from "@/components/Sidebar";
import Link from "next/link";

type Doc = {
  id: string;
  name: string;
  allowed_roles: string[];
  created_at: string;
};

const ALL_ROLES = ["employee", "manager", "hr", "admin"];

export default function DocumentsPage() {
  return (
    <RequireAuth>
      <div className="flex h-screen">
        <Sidebar />
        <div className="m-3 ml-0 flex-1 overflow-y-auto rounded-3xl bg-[#fdf8f3]/80 shadow-lg shadow-[#4a2c1a]/10 backdrop-blur-sm">
          <DocumentsManager />
        </div>
      </div>
    </RequireAuth>
  );
}

function DocumentsManager() {
  const { role, apiFetch } = useAuth();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);

  const canManage = role === "admin" || role === "hr";

  async function loadDocs() {
    setLoading(true);
    try {
      const res = await apiFetch("/documents");
      if (!res.ok) throw new Error("Failed to load documents");
      const data = await res.json();
      setDocs(data.documents || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadDocs();
  }, []);

  function toggleRole(r: string) {
    setSelectedRoles((cur) =>
      cur.includes(r) ? cur.filter((x) => x !== r) : [...cur, r]
    );
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("allowed_roles", selectedRoles.join(","));
      const res = await apiFetch("/upload", { method: "POST", body: form });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || "Upload failed");
      }
      setFile(null);
      setSelectedRoles([]);
      await loadDocs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this document?")) return;
    try {
      const res = await apiFetch(`/documents/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Delete failed");
      await loadDocs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  if (!canManage) {
    return (
      <div className="p-8">
        <p className="text-sm text-[#a68a6d]">
          You don&apos;t have permission to manage documents.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-8">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-[#3d2817]">Documents</h1>
      </div>

      <form
        onSubmit={handleUpload}
        className="mb-8 rounded-2xl border border-[#e8d3b8] bg-white/90 p-5 shadow-sm"
      >
        <h2 className="mb-3 text-sm font-medium text-[#3d2817]">Upload a document</h2>

        <label
          htmlFor="pdf-upload"
          className="mb-3 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-[#d9c3a4] bg-[#faf3e8] px-6 py-8 text-center hover:border-[#6f4523] hover:bg-[#f3e5d3]"
        >
          <span className="mb-2 text-2xl">📄</span>
          <span className="text-sm font-medium text-[#3d2817]">
            {file ? file.name : "Click to choose a PDF"}
          </span>
          <span className="mt-1 text-xs text-[#a68a6d]">or drag and drop here</span>
          <input
            id="pdf-upload"
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="hidden"
          />
        </label>

        <p className="mb-2 text-xs text-[#a68a6d]">
          Visible to (leave all unchecked for everyone):
        </p>
        <div className="mb-4 flex gap-3">
          {ALL_ROLES.map((r) => (
            <label key={r} className="flex items-center gap-1.5 text-sm text-[#6b5744]">
              <input
                type="checkbox"
                checked={selectedRoles.includes(r)}
                onChange={() => toggleRole(r)}
                className="accent-[#6f4523]"
              />
              {r}
            </label>
          ))}
        </div>
        <button
          type="submit"
          disabled={!file || uploading}
          className="rounded-xl bg-[#6f4523] px-4 py-2 text-sm font-medium text-white hover:bg-[#5a381c] disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </form>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <div className="rounded-2xl border border-[#e8d3b8] bg-white/90 shadow-sm">
        {loading ? (
          <p className="p-5 text-sm text-[#a68a6d]">Loading…</p>
        ) : docs.length === 0 ? (
          <p className="p-5 text-sm text-[#a68a6d]">No documents yet.</p>
        ) : (
          <ul className="divide-y divide-[#f0e2cc]">
            {docs.map((d) => (
              <li key={d.id} className="flex items-center justify-between p-4">
                <div>
                  <p className="text-sm font-medium text-[#3d2817]">{d.name}</p>
                  <p className="text-xs text-[#a68a6d]">
                    {d.allowed_roles?.join(", ") || "all roles"}
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <Link
                    href={`/documents/${d.id}/graph`}
                    className="text-sm text-[#6f4523] hover:text-[#5a381c]"
                  >
                    View Graph
                  </Link>
                  <button
                    onClick={() => handleDelete(d.id)}
                    className="text-sm text-red-600 hover:text-red-700"
                  >
                    Delete
                  </button>
                  <button
  onClick={async () => {
    const res = await apiFetch(`/documents/${d.id}/file`);
    const data = await res.json();
    if (data.url) window.open(data.url, "_blank");
  }}
  className="text-sm text-[#6f4523] hover:text-[#5a381c]"
>
  View
</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}