"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

type Doc = { id: string; name: string; allowed_roles: string[] };

export function DocumentPanel() {
  const { apiFetch, role } = useAuth();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [loading, setLoading] = useState(true);
  const canManage = role === "admin" || role === "hr";

  useEffect(() => {
    apiFetch("/documents")
      .then((r) => r.json())
      .then((d) => setDocs(d.documents || []))
      .finally(() => setLoading(false));
  }, []);

  return (
    <aside className="m-3 ml-0 hidden w-64 flex-col rounded-3xl bg-[#fdf8f3]/80 p-4 shadow-lg shadow-[#4a2c1a]/10 backdrop-blur-sm lg:flex">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-[#a68a6d]">
          📚 Knowledge Base
        </p>
        {canManage && (
          <Link href="/documents" className="text-xs text-[#6f4523] hover:text-[#5a381c]">
            Manage
          </Link>
        )}
      </div>
      {loading ? (
        <p className="text-xs text-[#a68a6d]">Loading…</p>
      ) : docs.length === 0 ? (
        <p className="text-xs text-[#a68a6d]">
          No documents available to you yet.
        </p>
      ) : (
        <ul className="space-y-2 overflow-y-auto">
          {docs.map((d) => (
            <li key={d.id} className="rounded-xl bg-white/80 px-3 py-2">
              <p className="truncate text-xs font-medium text-[#3d2817]" title={d.name}>
                📄 {d.name}
              </p>
              <p className="mt-0.5 truncate text-[10px] text-[#a68a6d]">
                {d.allowed_roles?.join(", ") || "all roles"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}