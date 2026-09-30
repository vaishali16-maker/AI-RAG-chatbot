"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "./auth-context";

export type Convo = { id: string; title: string; created_at: string };

export function useConversations() {
  const { apiFetch } = useAuth();
  const [conversations, setConversations] = useState<Convo[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/conversations");
      const data = await res.json();
      setConversations(data.conversations || []);
    } finally {
      setLoading(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { conversations, loading, refresh };
}