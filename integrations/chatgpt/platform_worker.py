import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
import socketio
from dotenv import load_dotenv
from psycopg import connect
from psycopg.rows import dict_row

from agenttrust_client import AgentTrustClient
from chatgpt_agent_with_agenttrust import ChatGPTAgentWithAgentTrust


def load_env_files() -> None:
    here = Path(__file__).resolve().parent
    repo_root = here.parent.parent
    for candidate in [
        repo_root / "backend" / ".env",
        repo_root / "platform" / ".env",
        repo_root / "platform" / ".env.local",
        here / ".env",
        repo_root / ".env",
    ]:
        if candidate.exists():
            load_dotenv(candidate, override=False)


def get_pool_kwargs() -> Dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if database_url and not os.getenv("DB_HOST"):
        kwargs: Dict[str, Any] = {"conninfo": database_url}
        if "sslmode=require" in database_url:
            kwargs["sslmode"] = "require"
        return kwargs

    kwargs = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD"),
        "dbname": os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or os.getenv("DB_USER") or "postgres",
    }
    if kwargs["host"] and "rds.amazonaws.com" in kwargs["host"]:
        kwargs["sslmode"] = "require"
    return kwargs


def now_utc() -> datetime:
    return datetime.now(UTC)


def normalize_json(value: Any) -> str:
    return json.dumps(value if value is not None else None)


def hash_step(previous_hash: str, payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"previousHash": previous_hash, "step": payload}, sort_keys=True).encode("utf-8")).hexdigest()


class PlatformWorkerRuntime:
    def __init__(self, job_id: str, worker_id: str, backend_url: str):
        self.job_id = job_id
        self.worker_id = worker_id
        self.backend_url = backend_url.rstrip("/")
        self.conn = connect(row_factory=dict_row, **get_pool_kwargs())
        self.socket = socketio.Client(reconnection=False, request_timeout=10)
        self.replay_sequence = 0
        self.progress_line_count = 0
        self.goal_names: List[str] = []
        self.completed_goals: set[int] = set()
        self.current_goal_index = 0
        self.last_step_detail: Dict[int, str] = {}
        self.last_meaningful_detail: str = ""
        self.last_meaningful_detail_step: Optional[int] = None

    def close(self) -> None:
        try:
            if self.socket.connected:
                self.socket.disconnect()
        except Exception:
            pass
        self.conn.close()

    def connect_socket(self) -> None:
        self.socket.connect(self.backend_url, transports=["websocket"])

    def emit(self, channel: str, payload: Dict[str, Any]) -> None:
        if self.socket.connected:
            self.socket.emit("platform:event", {"channel": channel, "payload": payload})

    def query_one(self, sql: str, values: tuple = ()) -> Optional[Dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(sql, values)
            return cur.fetchone()

    def execute(self, sql: str, values: tuple = ()) -> None:
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, values)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def seed_replay_sequence(self) -> None:
        row = self.query_one("SELECT MAX(sequence) AS max_sequence FROM replay_chunks WHERE job_id = %s", (self.job_id,))
        self.replay_sequence = int((row or {}).get("max_sequence") or 0)

    def next_replay_sequence(self) -> int:
        self.replay_sequence += 1
        return self.replay_sequence

    def load_job_context(self) -> Dict[str, Any]:
        row = self.query_one(
            """
            SELECT task, input, metadata, current_step_index AS current_step_index
            FROM agent_jobs
            WHERE id = %s
            """,
            (self.job_id,),
        )
        if not row:
            raise RuntimeError(f"Job {self.job_id} not found")
        return row

    def update_worker(self, status: str, metadata: Optional[Dict[str, Any]] = None, exit_code: Optional[int] = None) -> None:
        self.execute(
            """
            UPDATE worker_processes
            SET status = %s,
                pid = %s,
                host = %s,
                last_heartbeat_at = NOW(),
                exited_at = CASE WHEN %s::integer IS NOT NULL THEN NOW() ELSE exited_at END,
                exit_code = COALESCE(%s::integer, exit_code),
                metadata = COALESCE(%s::jsonb, metadata)
            WHERE id = %s
            """,
            (
                status,
                os.getpid(),
                os.getenv("COMPUTERNAME") or os.getenv("HOSTNAME") or "unknown",
                exit_code,
                exit_code,
                normalize_json(metadata) if metadata is not None else None,
                self.worker_id,
            ),
        )

    def update_job(self, **patch: Any) -> None:
        mappings = {
            "status": "status",
            "progress": "progress",
            "current_step": "current_step",
            "current_step_index": "current_step_index",
            "error": "error",
            "retry_count": "retry_count",
            "started_at": "started_at",
            "completed_at": "completed_at",
            "result": "result",
            "metadata": "metadata",
            "worker_id": "worker_id",
        }
        sets: List[str] = []
        values: List[Any] = []
        for key, value in patch.items():
            column = mappings.get(key)
            if not column:
                continue
            if key in {"result", "metadata"}:
                sets.append(f"{column} = %s::jsonb")
                values.append(normalize_json(value))
            else:
                sets.append(f"{column} = %s")
                values.append(value)
        if not sets:
            return
        values.extend([self.job_id])
        self.execute(
            f"UPDATE agent_jobs SET {', '.join(sets)}, last_heartbeat_at = NOW(), updated_at = NOW() WHERE id = %s",
            tuple(values),
        )

    def update_step(self, sequence: int, **patch: Any) -> None:
        mappings = {
            "status": "status",
            "retry_count": "retry_count",
            "failure_type": "failure_type",
            "failure_message": "failure_message",
            "result": "result",
            "started_at": "started_at",
            "finished_at": "finished_at",
        }
        sets: List[str] = []
        values: List[Any] = []
        for key, value in patch.items():
            column = mappings.get(key)
            if not column:
                continue
            if key == "result":
                sets.append(f"{column} = %s::jsonb")
                values.append(normalize_json(value))
            else:
                sets.append(f"{column} = %s")
                values.append(value)
        if not sets:
            return
        values.extend([self.job_id, sequence])
        self.execute(
            f"UPDATE agent_steps SET {', '.join(sets)}, updated_at = NOW() WHERE job_id = %s AND sequence = %s",
            tuple(values),
        )

    def get_step(self, sequence: int) -> Optional[Dict[str, Any]]:
        return self.query_one(
            """
            SELECT sequence, status, failure_type, failure_message
            FROM agent_steps
            WHERE job_id = %s AND sequence = %s
            """,
            (self.job_id, sequence),
        )

    def replace_steps(self, goals: List[str]) -> None:
        self.goal_names = goals
        self.completed_goals = set()
        previous_hash = "0"
        self.execute("DELETE FROM agent_steps WHERE job_id = %s", (self.job_id,))
        with self.conn.cursor() as cur:
            for sequence, goal in enumerate(goals):
                payload = {"id": f"goal-{sequence + 1}", "name": goal, "goal": goal, "action": "goal"}
                current_hash = hash_step(previous_hash, payload)
                cur.execute(
                    """
                    INSERT INTO agent_steps (
                        id, job_id, sequence, name, action, selector, selector_text, payload, verification,
                        status, retry_count, failure_type, hash, previous_hash, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, 'pending', 0, 'NONE', %s, %s, NOW(), NOW())
                    """,
                    (
                        f"{self.job_id}:goal:{sequence}",
                        self.job_id,
                        sequence,
                        goal,
                        "goal",
                        normalize_json(None),
                        None,
                        normalize_json(payload),
                        normalize_json(None),
                        current_hash,
                        previous_hash,
                    ),
                )
                previous_hash = current_hash
        self.conn.commit()

    def upsert_replay(self, event_type: str, payload: Dict[str, Any], step_sequence: Optional[int] = None) -> None:
        sequence = self.next_replay_sequence()
        record = dict(payload)
        if step_sequence is not None:
            record["stepSequence"] = step_sequence
        self.execute(
            """
            INSERT INTO replay_chunks (id, job_id, sequence, event_type, payload, created_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
            ON CONFLICT (job_id, sequence) DO UPDATE
            SET event_type = EXCLUDED.event_type, payload = EXCLUDED.payload
            """,
            (f"replay_{self.job_id}_{sequence}", self.job_id, sequence, event_type, normalize_json(record)),
        )
        self.emit("replay.updated", {"jobId": self.job_id})

    def create_correction(self, action_type: str, failure_type: str, failed_selector: Any, notes: str, domain: Optional[str] = None) -> None:
        self.execute(
            """
            INSERT INTO correction_memory (id, job_id, domain, action_type, failure_type, failed_selector, corrected_selector, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, NOW())
            """,
            (
                f"corr_{int(time.time() * 1000)}_{os.getpid()}",
                self.job_id,
                domain or "unknown",
                action_type,
                failure_type,
                normalize_json(failed_selector),
                normalize_json(None),
                notes,
            ),
        )

    def insert_metric(self, key: str, value: float, labels: Optional[Dict[str, Any]] = None) -> None:
        self.execute(
            """
            INSERT INTO metric_rollups (id, job_id, metric_key, metric_value, labels, created_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
            """,
            (f"metric_{int(time.time() * 1000)}_{os.getpid()}", self.job_id, key, value, normalize_json(labels or {})),
        )

    def build_user_message(self, job: Dict[str, Any]) -> str:
        job_input = job.get("input") or {}
        metadata = job.get("metadata") or {}
        input_metadata = job_input.get("metadata") or {}
        task = job.get("task") or job_input.get("task") or ""
        hints = job_input.get("steps") or []
        operator_prompts = metadata.get("operatorPrompts") or []
        sensitive_grants = metadata.get("sensitiveDataGrants") or []
        allowed_domains = job_input.get("allowedDomains") or []
        high_risk = input_metadata.get("highRiskKeywords") or []
        auditor_keywords = input_metadata.get("auditorKeywords") or []
        description = str(input_metadata.get("description") or "").strip()
        intent_summary = str(input_metadata.get("intentSummary") or "").strip()
        completion_criteria = str(input_metadata.get("completionCriteria") or "").strip()
        starting_context = str(input_metadata.get("startingContext") or "").strip()
        start_url = str(job_input.get("startUrl") or "").strip()
        verify_text = str(job_input.get("verifyText") or "").strip()
        planning_hints = input_metadata.get("planningHints") or []
        recovery_hints = input_metadata.get("recoveryHints") or []
        corrections: List[str] = []
        start_points: List[str] = []
        success_signals: List[str] = []
        failed_attempts: List[str] = []

        for step in hints:
            if not isinstance(step, dict):
                continue
            step_url = str(step.get("url") or "").strip()
            if step_url:
                start_points.append(step_url)
            verification = step.get("verification") or {}
            if isinstance(verification, dict):
                url_includes = str(verification.get("urlIncludes") or "").strip()
                text_visible = str(verification.get("textVisible") or "").strip()
                if url_includes:
                    success_signals.append(f"URL should include: {url_includes}")
                if text_visible:
                    success_signals.append(f"Visible text should include: {text_visible}")
        if start_url:
            start_points.append(start_url)
        if verify_text:
            success_signals.append(f'Visible text should include: {verify_text}')

        allowed_sensitive_profiles: List[str] = []
        for grant in sensitive_grants:
            if not isinstance(grant, dict):
                continue
            ref = str(grant.get("referenceKey") or "").strip()
            if not ref:
                continue
            label = str(grant.get("label") or "").strip()
            fields = grant.get("fieldNames") or []
            field_preview = ", ".join(str(field).strip() for field in fields[:6] if str(field).strip())
            if label and field_preview:
                allowed_sensitive_profiles.append(f"- {label} ({ref}) fields: {field_preview}")
            elif label:
                allowed_sensitive_profiles.append(f"- {label} ({ref})")
            elif field_preview:
                allowed_sensitive_profiles.append(f"- {ref} fields: {field_preview}")
            else:
                allowed_sensitive_profiles.append(f"- {ref}")

        if allowed_domains:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT domain, action_type, notes
                    FROM correction_memory
                    WHERE domain = ANY(%s)
                    ORDER BY created_at DESC
                    LIMIT 8
                    """,
                    (allowed_domains,),
                )
                corrections = [
                    f"- {row['domain']} / {row['action_type']}: {row['notes']}"
                    for row in cur.fetchall()
                    if row.get("notes")
                ]
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, failure_type, failure_message
                FROM agent_steps
                WHERE job_id = %s AND status IN ('failed', 'cancelled')
                ORDER BY sequence DESC
                LIMIT 5
                """,
                (self.job_id,),
            )
            failed_attempts = [
                f"- {row['name']} ({row['failure_type']}): {row['failure_message']}"
                for row in cur.fetchall()
                if row.get("failure_message")
            ]

        parts = [
            "Primary task:",
            task.strip(),
            "",
            "Execution rules:",
            "- Treat any configured steps as intent hints and starting goals, not as a rigid script.",
            "- Do not stop at an intermediate page if the requested end state has not been achieved yet.",
            "- Only finish when the user-visible outcome is complete, not when a search or navigation step merely succeeded.",
            "- If you hit friction, use the latest operator context and prior corrections to recover and continue.",
        ]
        if description:
            parts.append("")
            parts.append(f"Configuration description: {description}")
        if intent_summary:
            parts.append("")
            parts.append(f"Intent summary: {intent_summary}")
        if completion_criteria:
            parts.append("")
            parts.append(f"Completion criteria: {completion_criteria}")
        if allowed_sensitive_profiles:
            parts.append("")
            parts.append("Sensitive customer profiles attached to this operation:")
            parts.extend(allowed_sensitive_profiles)
            parts.append("Only use vault:// references from these attached profiles. If another profile is needed, ask the operator to attach it first.")
        if starting_context:
            parts.append("")
            parts.append(f"Starting context: {starting_context}")
        if start_points:
            parts.append("")
            parts.append("Preferred starting points:")
            for value in list(dict.fromkeys(start_points))[:5]:
                parts.append(f"- {value}")
        if success_signals:
            parts.append("")
            parts.append("Success signals to verify before finishing:")
            for value in list(dict.fromkeys(success_signals))[:8]:
                parts.append(f"- {value}")
        if hints:
            parts.append("")
            parts.append("Suggested starting goals:")
            for idx, step in enumerate(hints, start=1):
                label = step.get("goal") or step.get("name") or step.get("action") or f"Step {idx}"
                parts.append(f"{idx}. {label}")
        if planning_hints:
            parts.append("")
            parts.append("Planning hints:")
            for hint in planning_hints[:8]:
                cleaned = str(hint).strip()
                if cleaned:
                    parts.append(f"- {cleaned}")
        if recovery_hints:
            parts.append("")
            parts.append("Recovery hints:")
            for hint in recovery_hints[:8]:
                cleaned = str(hint).strip()
                if cleaned:
                    parts.append(f"- {cleaned}")
        if allowed_domains:
            parts.append("")
            parts.append(f"Allowed domains: {', '.join(allowed_domains)}")
        if high_risk:
            parts.append(f"High-risk keywords: {', '.join(high_risk)}")
        if auditor_keywords:
            parts.append(f"Auditor keywords: {', '.join(auditor_keywords)}")
        if operator_prompts:
            parts.append("")
            parts.append("Additional operator context:")
            for entry in operator_prompts[-5:]:
                parts.append(f"- {entry.get('prompt')}")
        if failed_attempts:
            parts.append("")
            parts.append("Recent failed attempts for this job:")
            parts.extend(failed_attempts)
        if corrections:
            parts.append("")
            parts.append("Relevant past corrections:")
            parts.extend(corrections)
        return "\n".join(parts).strip()

    def remember_step_detail(self, step_index: int, prefix: str, detail: str) -> None:
        cleaned_prefix = str(prefix or "").strip().upper()
        cleaned_detail = str(detail or "").strip()
        if not cleaned_detail:
            return

        if cleaned_prefix == "DONE" and cleaned_detail.lower() in {"done", "run finished", "agent run finished"}:
            return
        if cleaned_prefix == "GOAL" and cleaned_detail.lower().startswith("step "):
            return

        label_map = {
            "OBSERVE": "Observed",
            "ACT": "Action",
            "VERIFY": "Verification",
            "AUDIT": "Approval",
            "PLAN": "Plan",
            "DONE": "Run finished",
        }
        label = label_map.get(cleaned_prefix, cleaned_prefix.title() if cleaned_prefix else "Update")
        summary = f"{label}: {cleaned_detail}"
        self.last_step_detail[step_index] = summary
        self.last_meaningful_detail = summary
        self.last_meaningful_detail_step = step_index

    def unfinished_goal_reason(self, step_index: int) -> str:
        last_detail = (self.last_step_detail.get(step_index) or "").strip()
        if last_detail:
            return (
                f"Goal was not completed. Last meaningful activity: {last_detail}. "
                "The worker reached the end of the run without confirming the required end state."
            )
        fallback_step = self.last_meaningful_detail_step
        fallback_detail = (self.last_meaningful_detail or "").strip()
        if fallback_detail:
            if fallback_step is not None and fallback_step != step_index and 0 <= fallback_step < len(self.goal_names):
                fallback_goal = self.goal_names[fallback_step]
                return (
                    "Goal was not completed. "
                    f"The last meaningful activity before the run ended was on goal {fallback_step + 1} "
                    f"('{fallback_goal}'): {fallback_detail}. "
                    "The worker never confirmed the required end state for this goal."
                )
            return (
                f"Goal was not completed. Last meaningful activity before the run ended: {fallback_detail}. "
                "The worker never confirmed the required end state for this goal."
            )
        return (
            "Goal was not completed because the worker reached the end of the run "
            "without confirming the required end state."
        )

    def on_plan(self, sub_goals: List[str], plan_text: str, _state: Dict[str, Any]) -> None:
        goals = [str(goal).strip() for goal in sub_goals if str(goal).strip()]
        if not goals:
            goals = ["Complete the task"]
        self.replace_steps(goals)
        self.update_job(
            current_step=goals[0],
            current_step_index=0,
            progress=0,
        )
        self.emit("job.updated", {"id": self.job_id, "currentStep": goals[0], "currentStepIndex": 0, "progress": 0, "status": "running"})

    def on_progress(self, line: str, all_lines: List[str], state: Dict[str, Any]) -> None:
        if len(all_lines) <= self.progress_line_count:
            return
        self.progress_line_count = len(all_lines)
        self.current_goal_index = int(state.get("current_goal_index") or self.current_goal_index or 0)
        prefix, detail = (line.split("|", 1) + [""])[:2]
        step_index = min(self.current_goal_index, max(len(self.goal_names) - 1, 0))
        progress = round((len(self.completed_goals) / max(len(self.goal_names), 1)) * 100)
        if detail:
            self.remember_step_detail(step_index, prefix, detail)

        if prefix in {"OBSERVE", "ACT", "VERIFY", "AUDIT", "PLAN"} and self.goal_names:
            self.update_step(
                step_index,
                status="running",
                started_at=now_utc(),
                result={"message": detail},
            )
        if prefix == "VERIFY" and detail.lower().startswith("failed"):
            self.update_step(
                step_index,
                status="failed",
                failure_type="VERIFICATION_FAILED",
                failure_message=detail,
                result={"message": detail},
                finished_at=now_utc(),
            )
        if prefix == "GOAL":
            match = re.search(r"Step\s+(\d+)", detail)
            goal_index = int(match.group(1)) - 1 if match else step_index
            self.completed_goals.add(goal_index)
            self.update_step(
                goal_index,
                status="succeeded",
                failure_type="NONE",
                failure_message="Goal completed",
                result={"message": detail},
                finished_at=now_utc(),
            )
            progress = round((len(self.completed_goals) / max(len(self.goal_names), 1)) * 100)
        if prefix == "DONE":
            progress = 100

        self.upsert_replay("progress.line", {"line": line, "goalIndex": step_index}, step_sequence=step_index)
        self.update_job(
            status="running",
            current_step=detail or line,
            current_step_index=step_index,
            progress=progress,
        )
        self.emit(
            "job.updated",
            {
                "id": self.job_id,
                "status": "running",
                "currentStep": detail or line,
                "currentStepIndex": step_index,
                "progress": progress,
            },
        )

    def on_action_event(self, payload: Dict[str, Any]) -> None:
        result = payload.get("result") or {}
        action_type = payload.get("action_type") or "action"
        status = result.get("status") or "unknown"
        step_index = min(self.current_goal_index, max(len(self.goal_names) - 1, 0))
        browser_result = result.get("browser_result") or {}
        screenshot = result.get("screenshot")
        message = (
            browser_result.get("message")
            or result.get("message")
            or result.get("reason")
            or status
        )
        event_payload: Dict[str, Any] = {
            "actionType": action_type,
            "status": status,
            "message": message,
            "target": payload.get("target"),
            "url": payload.get("url"),
        }
        page_change = result.get("page_change") or browser_result.get("page_change") or {}
        if isinstance(page_change, dict) and page_change:
            event_payload["pageChange"] = page_change
        self.remember_step_detail(
            step_index,
            "ACT",
            f"{action_type.replace('_', ' ')} {status}: {message}",
        )
        if screenshot:
            event_payload["screenshotBase64"] = screenshot
            event_payload["screenshotMimeType"] = "image/jpeg"
        self.upsert_replay(f"action.{action_type}.{status}", event_payload, step_sequence=step_index)

        if status == "step_up_required":
            self.update_step(
                step_index,
                status="waiting_approval",
                failure_type="NONE",
                failure_message=message,
                result={"message": message},
            )
            self.update_job(status="waiting_approval", current_step="Waiting for approval", current_step_index=step_index)
            self.emit("job.updated", {"id": self.job_id, "status": "waiting_approval", "currentStep": "Waiting for approval"})
            return

        executed_ok = browser_result.get("success", True) if browser_result else status == "allowed"
        if status in {"denied", "error"} or not executed_ok:
            failure_type = "UNKNOWN"
            if "approval" in message.lower():
                failure_type = "POLICY_DENIED"
            elif "goal not achieved" in message.lower():
                failure_type = "GOAL_NOT_ACHIEVED"
            self.update_step(
                step_index,
                status="failed",
                retry_count=1,
                failure_type=failure_type,
                failure_message=message,
                result={"message": message},
                finished_at=now_utc(),
            )
            self.create_correction(
                action_type=action_type,
                failure_type=failure_type,
                failed_selector=payload.get("target") or payload.get("form_data"),
                notes=message,
                domain=(payload.get("url") and urlparse(payload["url"]).hostname) or None,
            )


class PlatformAgentTrustClient(AgentTrustClient):
    def __init__(self, runtime: PlatformWorkerRuntime):
        super().__init__(api_url=f"{runtime.backend_url}/api")
        self.runtime = runtime
        self.current_prompt_id = runtime.job_id

    def store_prompt(self, content: str, session_id: Optional[str] = None) -> Optional[str]:
        self.current_prompt_id = self.runtime.job_id
        return self.runtime.job_id

    def update_prompt_response(self, prompt_id: str, response_text: str) -> None:
        self.runtime.update_job(result={"response": response_text}, error=None)

    def update_prompt_progress(self, prompt_id: str, progress_text: str) -> None:
        return

    def on_platform_action_event(self, payload: Dict[str, Any]) -> None:
        self.runtime.on_action_event(payload)


def run_worker(job_id: str, worker_id: str) -> int:
    backend_url = os.getenv("PLATFORM_BACKEND_URL") or f"http://127.0.0.1:{os.getenv('PORT', '3000')}"
    runtime = PlatformWorkerRuntime(job_id, worker_id, backend_url)
    started_at = time.time()
    agent: Optional[ChatGPTAgentWithAgentTrust] = None

    try:
        runtime.connect_socket()
        runtime.seed_replay_sequence()
        job = runtime.load_job_context()
        job_input = job.get("input") or {}
        metadata = job_input.get("metadata") or {}
        high_risk = metadata.get("highRiskKeywords") or []
        if high_risk:
            os.environ["AGENTTRUST_AUDITOR_HIGH_RISK_KEYWORDS"] = ",".join(str(item) for item in high_risk)

        runtime.update_worker("running", {"jobId": job_id})
        runtime.update_job(
            status="running",
            started_at=now_utc(),
            current_step="Planning",
            progress=0,
            worker_id=worker_id,
            error=None,
        )
        runtime.emit("job.updated", {"id": job_id, "status": "running", "currentStep": "Planning", "progress": 0})

        client = PlatformAgentTrustClient(runtime)
        agent = ChatGPTAgentWithAgentTrust(enable_browser=True, headless=os.getenv("AGENTTRUST_HEADLESS", "true").lower() != "false", agenttrust_client=client)
        agent.on_platform_plan = runtime.on_plan
        agent.on_platform_progress = runtime.on_progress

        user_message = runtime.build_user_message(job)
        response_text = agent.chat(user_message)

        incomplete_goals = [idx for idx in range(len(runtime.goal_names)) if idx not in runtime.completed_goals]
        if runtime.goal_names and incomplete_goals:
            first_incomplete = incomplete_goals[0]
            existing_step = runtime.get_step(first_incomplete) or {}
            existing_failure_type = str(existing_step.get("failure_type") or "").strip()
            existing_failure_message = str(existing_step.get("failure_message") or "").strip()
            if existing_failure_type and existing_failure_type != "NONE" and existing_failure_message:
                raise RuntimeError(
                    f"Goal not achieved: {runtime.goal_names[first_incomplete]}. {existing_failure_message}"
                )
            failure_message = runtime.unfinished_goal_reason(first_incomplete)
            runtime.update_step(
                first_incomplete,
                status="failed",
                failure_type=existing_failure_type or "GOAL_NOT_ACHIEVED",
                failure_message=failure_message,
                result={"message": failure_message},
                finished_at=now_utc(),
            )
            raise RuntimeError(f"Goal not achieved: {runtime.goal_names[first_incomplete]}. {failure_message}")

        runtime.update_job(
            status="completed",
            progress=100,
            completed_at=now_utc(),
            current_step="Completed",
            result={"response": response_text},
            error=None,
        )
        runtime.update_worker("completed", {"response": response_text}, exit_code=0)
        runtime.insert_metric("job_duration_ms", round((time.time() - started_at) * 1000), {"status": "completed", "worker": "python"})
        runtime.emit("job.updated", {"id": job_id, "status": "completed", "currentStep": "Completed", "progress": 100})
        return 0
    except BaseException as exc:
        if isinstance(exc, SystemExit):
            code = exc.code
            if isinstance(code, str) and code.strip():
                message = code.strip()
            else:
                message = f"Worker exited during startup (code {code})"
        else:
            message = str(exc).strip() or exc.__class__.__name__
        runtime.update_job(
            status="cancelled" if "cancelled" in message.lower() else "failed",
            completed_at=now_utc(),
            error=message,
        )
        runtime.update_worker("failed", {"error": message}, exit_code=1)
        runtime.insert_metric("job_failure", 1, {"error": message, "worker": "python"})
        runtime.emit(
            "job.updated",
            {"id": job_id, "status": "cancelled" if "cancelled" in message.lower() else "failed", "error": message},
        )
        print(message, file=sys.stderr)
        return 1
    finally:
        try:
            if agent and agent.browser_executor and agent.browser_executor.browser:
                agent.browser_executor.browser.close()
        except Exception:
            pass
        runtime.close()


def main() -> int:
    load_env_files()
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobId", required=True)
    parser.add_argument("--workerId", required=True)
    args = parser.parse_args()
    return run_worker(args.jobId, args.workerId)


if __name__ == "__main__":
    sys.exit(main())
