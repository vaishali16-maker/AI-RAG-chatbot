"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { RequireAuth } from "@/lib/require-auth";
import { useAuth } from "@/lib/auth-context";

type Source = {
  document_id?: string;
  document_name?: string;
  source_file?: string;
  chunk_index?: number;
  similarity?: number;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
};

export default function HomePage() {
  return (
    <RequireAuth>
      <Chat />
    </RequireAuth>
  );
}

function Chat() {
  const { user, role, signOut, apiFetch } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;

    setMessages((m) => [...m, { role: "user", content: question }]);
    setInput("");
    setBusy(true);
    setError(null);

    try {
      const res = await apiFetch("/ask/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      setMessages((m) => [
        ...m,
        { role: "assistant", content: data.answer, sources: data.sources },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const canManageDocs = role === "admin" || role === "hr";

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div>
          <h1 className="text-sm font-semibold">Enterprise Knowledge Assistant</h1>
          <p className="text-xs text-slate-500">
            {user?.email} · {role ?? "…"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {canManageDocs && (
            <Link
              href="/documents"
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
            >
              Documents
            </Link>
          )}
          <button
            onClick={signOut}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 && (
          <p className="mx-auto max-w-2xl text-center text-sm text-slate-400">
            Ask a question about a document you have access to.
          </p>
        )}
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`rounded-2xl px-4 py-3 text-sm ${
                m.role === "user"
                  ? "ml-auto max-w-[80%] bg-slate-900 text-white"
                  : "max-w-[85%] bg-white border border-slate-200"
              }`}
            >
              <p className="whitespace-pre-wrap">{m.content}</p>
              {m.sources && m.sources.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-slate-100 pt-2">
                  {m.sources.map((s, j) => (
                    <p key={j} className="text-xs text-slate-400">
                      {s.document_name || s.source_file}
                      {typeof s.similarity === "number" &&
                        ` · ${(s.similarity * 100).toFixed(0)}% match`}
                    </p>
                  ))}
                </div>
              )}
            </div>
          ))}
          {busy && <p className="text-sm text-slate-400">Thinking…</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div ref={bottomRef} />
        </div>
      </main>

      <form
        onSubmit={handleSend}
        className="border-t border-slate-200 bg-white px-6 py-4"
      >
        <div className="mx-auto flex max-w-2xl gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question…"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}