"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { RequireAuth } from "@/lib/require-auth";
import { useAuth } from "@/lib/auth-context";
import { Sidebar } from "@/components/Sidebar";

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
      <div className="flex h-screen">
        <Sidebar />
        <Chat />
      </div>
    </RequireAuth>
  );
}

function Chat() {
  const { apiFetch } = useAuth();
  const searchParams = useSearchParams();
  const urlConvoId = searchParams.get("conversation");
  const [conversationId, setConversationId] = useState<string | null>(urlConvoId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setConversationId(urlConvoId);
    if (!urlConvoId) setMessages([]);
  }, [urlConvoId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!conversationId) return;
    apiFetch(`/conversations/${conversationId}/messages`)
      .then((r) => r.json())
      .then((d) => setMessages(d.messages || []));
  }, [conversationId, apiFetch]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;

    setMessages((m) => [...m, { role: "user", content: question }]);
    setInput("");
    setBusy(true);
    setError(null);

    try {
      const res = await apiFetch("/ask/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, conversation_id: conversationId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      if (!conversationId) {
        window.history.replaceState(null, "", `/?conversation=${data.conversation_id}`);
      }
      setConversationId(data.conversation_id);
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

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(e as unknown as React.FormEvent);
    }
  }

  return (
    <div className="m-3 ml-0 flex flex-1 flex-col rounded-3xl bg-[#fdf8f3]/80 shadow-lg shadow-[#4a2c1a]/10 backdrop-blur-sm">
      <header className="border-b border-[#e8d3b8] px-6 py-4">
        <h1 className="text-sm font-semibold text-[#3d2817]">
          {conversationId ? "Conversation" : "New conversation"}
        </h1>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 && (
          <div className="mx-auto flex max-w-2xl flex-col items-center gap-2 pt-20 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#6f4523] text-2xl">
              🤖
            </div>
            <p className="text-sm text-[#a68a6d]">
              Ask me anything about a document you have access to.
            </p>
          </div>
        )}
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`rounded-2xl px-4 py-3 text-sm shadow-sm ${
                m.role === "user"
                  ? "ml-auto max-w-[80%] bg-[#6f4523] text-white"
                  : "max-w-[85%] border border-[#e8d3b8] bg-white/90 text-[#3d2817]"
              }`}
            >
              <p className="whitespace-pre-wrap">{m.content}</p>
              {m.sources && m.sources.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-[#f0e2cc] pt-2">
                  {m.sources.map((s, j) => (
                    <p key={j} className="text-xs text-[#a68a6d]">
                      {s.document_name || s.source_file}
                      {typeof s.similarity === "number" &&
                        ` · ${(s.similarity * 100).toFixed(0)}% match`}
                    </p>
                  ))}
                </div>
              )}
            </div>
          ))}
          {busy && <p className="text-sm text-[#a68a6d]">Thinking…</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div ref={bottomRef} />
        </div>
      </main>

      <form onSubmit={handleSend} className="border-t border-[#e8d3b8] px-6 py-4">
        <div className="mx-auto flex max-w-2xl gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question…"
            className="flex-1 rounded-xl border border-[#d9c3a4] bg-white px-3 py-2 text-sm text-[#3d2817] focus:border-[#6f4523] focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-xl bg-[#6f4523] px-4 py-2 text-sm font-medium text-white hover:bg-[#5a381c] disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}