"""
Action History RAG for AgentTrust Browser Agent
================================================
Persists successful action sequences and retrieves similar past tasks
to improve planning and execution consistency.

Storage: Local JSON lines file + in-memory TF-IDF index.
No external vector DB required — keeps the integration lightweight.

How it works:
  1. After each successful chat(), the action sequence is saved with
     the user request as the "task description."
  2. Before planning a new task, the RAG retrieves the top-K most
     similar past tasks and returns their action sequences.
  3. These are injected into the planner prompt so the LLM can follow
     proven patterns instead of improvising from scratch.

Usage:
    from action_history_rag import ActionHistoryRAG
    rag = ActionHistoryRAG()
    rag.record(task="Search Amazon for headphones", actions=[...], success=True)
    similar = rag.retrieve("Find wireless earbuds on Amazon", top_k=3)
"""

import json
import os
import time
import math
import re
from typing import List, Dict, Any, Optional
from datetime import datetime


# ---------------------------------------------------------------------------
# Default storage location: next to the script, in a .data/ folder
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_STORE_PATH = os.path.join(_SCRIPT_DIR, ".data", "action_history.jsonl")


class ActionHistoryRAG:
    """
    Lightweight action-history retrieval using TF-IDF cosine similarity.

    Each record is a JSON line:
        {
            "task": "user request text",
            "actions": [ { "tool": "...", "args": {...}, "result_status": "..." }, ... ],
            "domains": ["amazon.com", ...],
            "success": true,
            "duration_s": 12.3,
            "timestamp": "2026-03-07T10:00:00",
            "action_count": 5
        }

    On startup, records are loaded into memory and a TF-IDF vocabulary is
    built. Retrieval is a simple cosine similarity search — fast enough for
    hundreds of past tasks (sub-millisecond).
    """

    def __init__(self, store_path: Optional[str] = None, max_records: int = 500):
        """
        Args:
            store_path: Path to the JSONL file. Defaults to .data/action_history.jsonl
            max_records: Maximum records kept in memory (oldest dropped first)
        """
        self.store_path = store_path or os.getenv(
            "ACTION_HISTORY_PATH", _DEFAULT_STORE_PATH
        )
        self.max_records = max_records
        self._records: List[Dict[str, Any]] = []
        self._vocab: Dict[str, int] = {}  # word → index
        self._idf: List[float] = []       # idf weight per vocab term
        self._tfidf_matrix: List[List[float]] = []  # one vector per record
        self._dirty = False               # set when records added but index not rebuilt

        # Ensure storage directory exists
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)

        # Load existing history
        self._load()
        if self._records:
            self._build_index()
            print(f"📚 Action history loaded: {len(self._records)} past tasks")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        task: str,
        actions: List[Dict[str, Any]],
        success: bool = True,
        domains: Optional[List[str]] = None,
        duration_s: Optional[float] = None,
    ) -> None:
        """
        Save a completed task and its action sequence.

        Args:
            task: The original user request.
            actions: List of action dicts, each with at least {tool, args, result_status}.
            success: Whether the task completed successfully.
            domains: List of domains visited during the task.
            duration_s: Time taken in seconds.
        """
        if not task or not actions:
            return

        entry = {
            "task": task.strip(),
            "actions": actions,
            "domains": domains or [],
            "success": success,
            "duration_s": round(duration_s, 2) if duration_s else None,
            "timestamp": datetime.now().isoformat(),
            "action_count": len(actions),
        }

        self._records.append(entry)

        # Trim oldest if over limit
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records :]

        self._dirty = True
        self._save_append(entry)

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        success_only: bool = True,
        min_actions: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most similar past tasks.

        Args:
            query: Current user request to match against.
            top_k: Number of results to return.
            success_only: Only return tasks that succeeded.
            min_actions: Minimum number of actions a task must have.

        Returns:
            List of record dicts, most similar first. Each includes a
            "similarity" score (0-1).
        """
        if not self._records:
            return []

        if self._dirty:
            self._build_index()

        query_vec = self._text_to_tfidf(self._tokenize(query))
        if not query_vec or all(v == 0 for v in query_vec):
            return []

        scored = []
        for i, rec in enumerate(self._records):
            if success_only and not rec.get("success", True):
                continue
            if rec.get("action_count", 0) < min_actions:
                continue

            sim = self._cosine_sim(query_vec, self._tfidf_matrix[i])
            if sim > 0.05:  # minimum relevance threshold
                scored.append((sim, i))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for sim, idx in scored[:top_k]:
            rec = dict(self._records[idx])
            rec["similarity"] = round(sim, 4)
            results.append(rec)

        return results

    def format_for_prompt(
        self, similar_tasks: List[Dict[str, Any]], max_chars: int = 2000
    ) -> str:
        """
        Format retrieved tasks into a compact string for LLM prompt injection.

        Args:
            similar_tasks: Output from retrieve().
            max_chars: Maximum total characters for the formatted text.

        Returns:
            Formatted string ready to inject into a system/user prompt.
        """
        if not similar_tasks:
            return ""

        lines = ["SIMILAR PAST TASKS (use these as reference):"]
        used = len(lines[0])

        for i, task in enumerate(similar_tasks, 1):
            header = f"\n--- Past task {i} (similarity: {task['similarity']:.0%}) ---"
            task_line = f"Request: {task['task']}"

            # Compact action summary: tool(key_arg) → status
            action_lines = []
            for act in task.get("actions", [])[:10]:
                tool = act.get("tool", "?")
                status = act.get("result_status", "ok")

                # Extract the most identifying argument
                args = act.get("args", {})
                key_arg = ""
                if isinstance(args, dict):
                    for k in ("url", "text", "href", "link_text", "domain"):
                        if k in args and args[k]:
                            val = str(args[k])[:60]
                            key_arg = f'({k}="{val}")'
                            break
                    if not key_arg:
                        # Try target.text or target.id
                        target = args.get("target", {})
                        if isinstance(target, dict):
                            tid = target.get("id") or target.get("text", "")
                            if tid:
                                key_arg = f'(target="{str(tid)[:40]}")'

                action_lines.append(f"  {tool}{key_arg} → {status}")

            actions_text = "\n".join(action_lines)
            block = f"{header}\n{task_line}\nActions:\n{actions_text}"

            if used + len(block) > max_chars:
                break

            lines.append(block)
            used += len(block)

        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Return basic statistics about the stored history."""
        if not self._records:
            return {"total": 0}

        successes = sum(1 for r in self._records if r.get("success", True))
        domains = set()
        for r in self._records:
            domains.update(r.get("domains", []))

        return {
            "total": len(self._records),
            "successes": successes,
            "failures": len(self._records) - successes,
            "unique_domains": len(domains),
            "domains": sorted(domains)[:20],
            "oldest": self._records[0].get("timestamp", "?"),
            "newest": self._records[-1].get("timestamp", "?"),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load records from the JSONL file."""
        if not os.path.isfile(self.store_path):
            return

        records = []
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print(f"⚠️  Error loading action history: {e}")
            return

        # Keep only the most recent max_records
        if len(records) > self.max_records:
            records = records[-self.max_records :]

        self._records = records

    def _save_append(self, entry: Dict[str, Any]) -> None:
        """Append a single record to the JSONL file."""
        try:
            with open(self.store_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            print(f"⚠️  Error saving action history: {e}")

    # ------------------------------------------------------------------
    # TF-IDF index
    # ------------------------------------------------------------------

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenizer: lowercase, split on non-alphanumeric, remove stopwords."""
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "can", "shall",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "and",
            "but", "or", "nor", "not", "no", "so", "if", "then", "than",
            "too", "very", "just", "about", "above", "below", "between",
            "it", "its", "it's", "this", "that", "these", "those", "i",
            "me", "my", "we", "our", "you", "your", "he", "she", "they",
            "them", "their", "what", "which", "who", "when", "where",
            "how", "all", "each", "every", "both", "few", "more", "most",
            "other", "some", "such", "only", "own", "same", "up", "down",
        }
        return [t for t in tokens if t not in stopwords and len(t) > 1]

    def _record_to_text(self, record: Dict[str, Any]) -> str:
        """Convert a record into a searchable text blob."""
        parts = [record.get("task", "")]

        # Add domain names
        for d in record.get("domains", []):
            parts.append(d.replace(".", " "))

        # Add tool names and key arguments from actions
        for act in record.get("actions", []):
            if isinstance(act, str):
                parts.append(act)
                continue
            parts.append(act.get("tool", ""))
            args = act.get("args", {})
            if isinstance(args, dict):
                for k in ("url", "text", "href", "link_text", "domain"):
                    if k in args and args[k]:
                        parts.append(str(args[k]))

        return " ".join(parts)

    def _build_index(self) -> None:
        """Build the TF-IDF index from all records."""
        if not self._records:
            return

        # Tokenize all documents
        docs = [self._tokenize(self._record_to_text(r)) for r in self._records]

        # Build vocabulary
        vocab = {}
        for doc in docs:
            for token in set(doc):
                if token not in vocab:
                    vocab[token] = len(vocab)
        self._vocab = vocab

        n = len(docs)
        vocab_size = len(vocab)

        # Compute document frequency for each term
        df = [0] * vocab_size
        for doc in docs:
            seen = set()
            for token in doc:
                idx = vocab.get(token)
                if idx is not None and idx not in seen:
                    df[idx] += 1
                    seen.add(idx)

        # IDF = log(N / df) + 1  (smoothed)
        self._idf = [
            math.log(n / max(d, 1)) + 1.0 for d in df
        ]

        # Build TF-IDF vectors
        self._tfidf_matrix = []
        for doc in docs:
            vec = [0.0] * vocab_size
            # Term frequency
            for token in doc:
                idx = vocab.get(token)
                if idx is not None:
                    vec[idx] += 1.0
            # TF * IDF + L2 normalize
            norm_sq = 0.0
            for i in range(vocab_size):
                if vec[i] > 0:
                    vec[i] = (1 + math.log(vec[i])) * self._idf[i]
                    norm_sq += vec[i] ** 2
            norm = math.sqrt(norm_sq) if norm_sq > 0 else 1.0
            self._tfidf_matrix.append([v / norm for v in vec])

        self._dirty = False

    def _text_to_tfidf(self, tokens: List[str]) -> List[float]:
        """Convert a tokenized query into a TF-IDF vector."""
        if not self._vocab:
            return []

        vec = [0.0] * len(self._vocab)
        for token in tokens:
            idx = self._vocab.get(token)
            if idx is not None:
                vec[idx] += 1.0

        # TF * IDF + normalize
        norm_sq = 0.0
        for i in range(len(vec)):
            if vec[i] > 0:
                vec[i] = (1 + math.log(vec[i])) * self._idf[i]
                norm_sq += vec[i] ** 2

        norm = math.sqrt(norm_sq) if norm_sq > 0 else 1.0
        return [v / norm for v in vec]

    @staticmethod
    def _cosine_sim(a: List[float], b: List[float]) -> float:
        """Cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        # Vectors are already normalized, but guard against edge cases
        return max(0.0, min(1.0, dot))
