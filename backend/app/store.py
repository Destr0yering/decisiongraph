"""SQLite decision ledger with explicit state transitions and audit events."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from .models import (
    Decision,
    DecisionContext,
    DecisionStatus,
    InvalidationRecord,
    ProjectionStatus,
)


class DecisionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    context_json TEXT,
                    created_at TEXT NOT NULL,
                    approved_at TEXT,
                    supersedes TEXT,
                    datahub_urn TEXT,
                    projection_status TEXT NOT NULL,
                    projection_error TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS invalidation_events (
                    id TEXT PRIMARY KEY,
                    asset_urn TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    impacted_decision_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS
                    one_replacement_per_decision
                    ON decisions(supersedes)
                    WHERE supersedes IS NOT NULL;
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(decisions)"
                ).fetchall()
            }
            if "context_json" not in columns:
                connection.execute(
                    "ALTER TABLE decisions ADD COLUMN context_json TEXT"
                )

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> Decision:
        return Decision(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            summary=row["summary"],
            evidence=json.loads(row["evidence_json"]),
            dependencies=json.loads(row["dependencies_json"]),
            context=(
                DecisionContext.model_validate_json(row["context_json"])
                if row["context_json"]
                else None
            ),
            created_at=row["created_at"],
            approved_at=row["approved_at"],
            supersedes=row["supersedes"],
            datahub_urn=row["datahub_urn"],
            projection_status=row["projection_status"],
            projection_error=row["projection_error"],
        )

    def _audit(
        self,
        connection: sqlite3.Connection,
        decision_id: UUID | str,
        event_type: str,
        details: dict[str, object] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events(decision_id, event_type, details_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(decision_id),
                event_type,
                json.dumps(details or {}, sort_keys=True),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def create(self, decision: Decision) -> Decision:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO decisions(
                    id, title, status, summary, evidence_json, dependencies_json,
                    context_json,
                    created_at, approved_at, supersedes, datahub_urn,
                    projection_status, projection_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(decision.id),
                    decision.title,
                    decision.status.value,
                    decision.summary,
                    json.dumps(decision.evidence),
                    json.dumps([item.model_dump(mode="json") for item in decision.dependencies]),
                    (
                        decision.context.model_dump_json()
                        if decision.context
                        else None
                    ),
                    decision.created_at.isoformat(),
                    decision.approved_at.isoformat() if decision.approved_at else None,
                    str(decision.supersedes) if decision.supersedes else None,
                    decision.datahub_urn,
                    decision.projection_status.value,
                    decision.projection_error,
                ),
            )
            self._audit(connection, decision.id, "DECISION_CREATED")
        return decision

    def get(self, decision_id: UUID | str) -> Decision | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM decisions WHERE id = ?", (str(decision_id),)
            ).fetchone()
        return self._decision_from_row(row) if row else None

    def list(self) -> list[Decision]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM decisions ORDER BY created_at DESC"
            ).fetchall()
        return [self._decision_from_row(row) for row in rows]

    def replacement_for(self, decision_id: UUID | str) -> Decision | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM decisions WHERE supersedes = ?",
                (str(decision_id),),
            ).fetchone()
        return self._decision_from_row(row) if row else None

    def approve(self, decision_id: UUID) -> Decision | None:
        approved_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM decisions WHERE id = ?",
                (str(decision_id),),
            ).fetchone()
            if not existing:
                return None
            decision = self._decision_from_row(existing)
            cursor = connection.execute(
                """
                UPDATE decisions
                SET status = ?, approved_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    DecisionStatus.APPROVED.value,
                    approved_at,
                    str(decision_id),
                    DecisionStatus.PENDING_APPROVAL.value,
                ),
            )
            if cursor.rowcount:
                self._audit(
                    connection,
                    decision_id,
                    "DECISION_APPROVED",
                    {"supersedes": str(decision.supersedes) if decision.supersedes else None},
                )
                if decision.supersedes:
                    superseded = connection.execute(
                        """
                        UPDATE decisions
                        SET status = ?
                        WHERE id = ? AND status = ?
                        """,
                        (
                            DecisionStatus.SUPERSEDED.value,
                            str(decision.supersedes),
                            DecisionStatus.REVALIDATION_REQUIRED.value,
                        ),
                    )
                    if superseded.rowcount:
                        self._audit(
                            connection,
                            decision.supersedes,
                            "DECISION_SUPERSEDED",
                            {"replacement_decision_id": str(decision.id)},
                        )
        return self.get(decision_id)

    def revalidate(
        self,
        decision_id: UUID,
        replacement: Decision | None = None,
    ) -> Decision | None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM decisions WHERE id = ?",
                (str(decision_id),),
            ).fetchone()
            if not existing:
                return None
            prior = self._decision_from_row(existing)
            if prior.status is not DecisionStatus.REVALIDATION_REQUIRED:
                return prior

            replacement_row = connection.execute(
                "SELECT id FROM decisions WHERE supersedes = ?",
                (str(prior.id),),
            ).fetchone()
            if replacement_row:
                return self.get(replacement_row["id"])

            replacement = replacement or Decision(
                title=f"{prior.title} (Revalidated)",
                summary=(
                    f"{prior.summary} Revalidated after an upstream dependency change "
                    "required a fresh approval."
                ),
                evidence=[
                    *prior.evidence,
                    f"Supersedes decision {prior.id} after upstream dependency changes.",
                ],
                dependencies=prior.dependencies,
                context=prior.context,
                supersedes=prior.id,
            )
            if replacement.supersedes != prior.id:
                raise ValueError("Replacement must supersede the invalidated decision")
            connection.execute(
                """
                INSERT INTO decisions(
                    id, title, status, summary, evidence_json, dependencies_json,
                    context_json,
                    created_at, approved_at, supersedes, datahub_urn,
                    projection_status, projection_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(replacement.id),
                    replacement.title,
                    replacement.status.value,
                    replacement.summary,
                    json.dumps(replacement.evidence),
                    json.dumps(
                        [item.model_dump(mode="json") for item in replacement.dependencies]
                    ),
                    (
                        replacement.context.model_dump_json()
                        if replacement.context
                        else None
                    ),
                    replacement.created_at.isoformat(),
                    None,
                    str(replacement.supersedes),
                    None,
                    replacement.projection_status.value,
                    None,
                ),
            )
            self._audit(
                connection,
                prior.id,
                "DECISION_REVALIDATION_STARTED",
                {"replacement_decision_id": str(replacement.id)},
            )
            self._audit(
                connection,
                replacement.id,
                "DECISION_CREATED",
                {"revalidation_of": str(prior.id)},
            )
        return self.get(replacement.id)

    def set_projection(
        self,
        decision_id: UUID,
        status: ProjectionStatus,
        *,
        datahub_urn: str | None = None,
        error: str | None = None,
    ) -> Decision:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE decisions
                SET projection_status = ?, datahub_urn = COALESCE(?, datahub_urn),
                    projection_error = ?
                WHERE id = ?
                """,
                (status.value, datahub_urn, error, str(decision_id)),
            )
            self._audit(
                connection,
                decision_id,
                f"PROJECTION_{status.value}",
                {"datahub_urn": datahub_urn, "error": error},
            )
        decision = self.get(decision_id)
        if decision is None:
            raise KeyError(decision_id)
        return decision

    def invalidate(
        self,
        asset_urn: str,
        event_type: str,
        severity: str,
    ) -> list[Decision]:
        impacted: list[Decision] = []
        event_id = uuid4()
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM decisions WHERE status = ?",
                (DecisionStatus.APPROVED.value,),
            ).fetchall()
            for row in rows:
                decision = self._decision_from_row(row)
                if not any(edge.asset_urn == asset_urn for edge in decision.dependencies):
                    continue
                connection.execute(
                    "UPDATE decisions SET status = ? WHERE id = ?",
                    (DecisionStatus.REVALIDATION_REQUIRED.value, str(decision.id)),
                )
                self._audit(
                    connection,
                    decision.id,
                    "DECISION_INVALIDATED",
                    {
                        "asset_urn": asset_urn,
                        "event_type": event_type,
                        "severity": severity,
                        "invalidation_event_id": str(event_id),
                    },
                )
                impacted.append(
                    decision.model_copy(
                        update={"status": DecisionStatus.REVALIDATION_REQUIRED}
                    )
                )
            connection.execute(
                """
                INSERT INTO invalidation_events(
                    id, asset_urn, event_type, severity,
                    impacted_decision_ids_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event_id),
                    asset_urn,
                    event_type,
                    severity,
                    json.dumps([str(item.id) for item in impacted]),
                    created_at,
                ),
            )
        return impacted

    def invalidation_events(self) -> list[InvalidationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, asset_urn, event_type, severity,
                       impacted_decision_ids_json, created_at
                FROM invalidation_events ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            InvalidationRecord(
                id=row["id"],
                asset_urn=row["asset_urn"],
                event_type=row["event_type"],
                severity=row["severity"],
                impacted_decision_ids=json.loads(
                    row["impacted_decision_ids_json"]
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def audit_events(self, decision_id: UUID) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_type, details_json, created_at
                FROM audit_events WHERE decision_id = ? ORDER BY id
                """,
                (str(decision_id),),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
