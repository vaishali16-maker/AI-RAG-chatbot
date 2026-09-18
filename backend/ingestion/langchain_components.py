import os
from typing import List
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_cohere import CohereEmbeddings
from langchain_groq import ChatGroq

# Embeddings — replaces raw co.embed() calls
embeddings = CohereEmbeddings(
    cohere_api_key=os.environ.get("COHERE_API_KEY"),
    model="embed-english-light-v3.0",
)

# LLM — replaces raw requests.post() to Groq
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=os.environ.get("GROQ_API_KEY"),
    temperature=0,
)


class SupabaseMatchRetriever(BaseRetriever):
    """LangChain-compatible retriever wrapping our existing
    Supabase match_documents RPC (keeps match_threshold support
    that the built-in SupabaseVectorStore doesn't expose)."""

    match_count: int = 3
    match_threshold: float = 0.15

    def _get_relevant_documents(self, query: str) -> List[Document]:
        from backend.ingestion.ingestion import search_documents  # local import avoids circulars
        results = search_documents(
            query, match_count=self.match_count, match_threshold=self.match_threshold
        )
        return [
            Document(
                page_content=r["content"],
                metadata={
                    "source_file": r.get("source_file"),
                    "chunk_index": r.get("chunk_index"),
                    "similarity": r.get("similarity"),
                },
            )
            for r in results
        ]