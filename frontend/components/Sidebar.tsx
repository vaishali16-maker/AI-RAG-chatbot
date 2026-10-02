"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useConversations } from "@/lib/conversations";

export function Sidebar() {
  const { user, role, signOut, apiFetch } = useAuth();
  const { conversations, loading } = useConversations();
  const pathname = usePathname();
  const router = useRouter();

  const [stats, setStats] = useState<{ cache_hit_rate: number; avg_latency_ms: number; total_requests: number } | null>(null);

  useEffect(() => {
  apiFetch("/stats").then(r => r.json()).then(setStats).catch(() => {});
  const interval = setInterval(() => {
    apiFetch("/stats").then(r => r.json()).then(setStats).catch(() => {});
  }, 5000);
  return () => clearInterval(interval);
}, []);
  const activeConvoId =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("conversation")
      : null;

  const canManageDocs = role === "admin" || role === "hr";
  const initials = (user?.email || "?").slice(0, 2).toUpperCase();

  return (
    <aside className="m-3 flex h-[calc(100vh-1.5rem)] w-64 flex-col rounded-3xl bg-[#fdf8f3]/80 p-3 shadow-lg shadow-[#4a2c1a]/10 backdrop-blur-sm">
      {/* Logo / app name */}
      <div className="flex items-center gap-2 px-2 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#6f4523] text-sm">
          🤖
        </div>
        <span className="text-sm font-semibold text-[#3d2817]">Knowledge Assistant</span>
      </div>

      {/* New chat */}
      <button
        onClick={() => { window.history.pushState(null, "", "/"); window.location.href = "/"; }}
        className="mb-3 flex w-full items-center gap-2 rounded-2xl bg-[#6f4523] px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-[#5a381c]"
      >
        + New chat
      </button>

      {canManageDocs && (
        <Link
          href="/documents"
          className={`mb-3 block rounded-2xl px-4 py-2.5 text-sm font-medium ${
            pathname === "/documents"
              ? "bg-[#e8d3b8] text-[#3d2817]"
              : "text-[#6b5744] hover:bg-[#f3e5d3]/60"
          }`}
        >
          📄 Document Uploads
        </Link>
      )}

      {/* Conversation history */}
      <div className="flex-1 overflow-y-auto">
        <p className="mb-1 px-3 text-xs font-semibold uppercase tracking-wide text-[#a68a6d]">
          History
        </p>
        {loading ? (
          <p className="px-3 py-2 text-xs text-[#a68a6d]">Loading…</p>
        ) : conversations.length === 0 ? (
          <p className="px-3 py-2 text-xs text-[#a68a6d]">No conversations yet.</p>
        ) : (
          <ul className="space-y-1">
            {conversations.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/?conversation=${c.id}`}
                  className={`block truncate rounded-2xl px-3 py-2 text-sm ${
                    activeConvoId === c.id
                      ? "bg-[#e8d3b8] font-medium text-[#3d2817]"
                      : "text-[#6b5744] hover:bg-[#f3e5d3]/60"
                  }`}
                  title={c.title}
                >
                  {c.title}
                </Link>
              </li>
            ))}
          </ul>
         )}
      </div>

      {/* Stats */}
      {stats && stats.total_requests > 0 && (
  <div className="mb-2 rounded-2xl bg-[#f3e5d3]/60 px-3 py-2 text-xs text-[#6b5744]">
    <p className="mb-1 font-semibold uppercase tracking-wide text-[10px] text-[#a68a6d]">
      ⚡ Usage
    </p>
    <p>{stats.total_requests} requests · {Math.round(stats.cache_hit_rate * 100)}% cached</p>
    <p>avg {stats.avg_latency_ms}ms response</p>
  </div>
)}

      {/* User profile, pinned bottom */}
      <div className="mt-2 border-t border-[#e8d3b8] pt-2">
        <div className="flex items-center gap-2 rounded-2xl px-2 py-2 hover:bg-[#f3e5d3]/60">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#6f4523] text-xs font-semibold text-white">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-[#3d2817]">{user?.email}</p>
            <p className="text-xs capitalize text-[#a68a6d]">{role ?? "…"}</p>
          </div>
          <button
            onClick={signOut}
            title="Sign out"
            className="rounded-lg p-1.5 text-[#a68a6d] hover:bg-[#e8d3b8] hover:text-[#3d2817]"
          >
            ⏻
          </button>
        </div>
      </div>
    </aside>
  );
}