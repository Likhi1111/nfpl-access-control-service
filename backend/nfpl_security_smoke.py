"""NFPL API security smoke checks using a rolled-back PostgreSQL transaction.

Run from backend/: python nfpl_security_smoke.py
Requires your existing NFPL_DB_PASSWORD or DATABASE_URL in this terminal.

The API may call session.commit(), but all writes are confined to an outer
transaction that is rolled back after these checks.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import Grant, Job, Role, engine_for
from app.main import app, db_session

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))


def call(client: TestClient, method: str, path: str, actor_id: int, payload=None):
    return client.request(method, path, headers={"X-Actor-Id": str(actor_id)}, json=payload)


def expect_http(client, title, method, path, actor_id, payload, expected):
    try:
        resp = call(client, method, path, actor_id, payload)
        record(title, resp.status_code == expected, f"HTTP {resp.status_code}, expected {expected}")
        return resp
    except Exception as exc:
        record(title, False, f"{type(exc).__name__}: {exc}")
        return None


def expect_decision(client, title, user_id, action, job_id, expected_allowed, expected_reason):
    resp = call(client, "POST", "/api/authorize", user_id,
                {"user_id": user_id, "action": action, "job_id": job_id})
    body = resp.json() if resp.status_code == 200 else {}
    ok = (resp.status_code == 200 and body.get("allowed") is expected_allowed
          and body.get("reason_code") == expected_reason)
    record(title, ok, f"HTTP {resp.status_code}; {body if resp.status_code == 200 else resp.text[:180]}")


def main() -> int:
    engine = engine_for()
    # All API commits are SAVEPOINT releases inside this outer transaction.
    with engine.connect() as connection:
        outer = connection.begin()
        def test_session():
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                yield db
        app.dependency_overrides[db_session] = test_session
        try:
            with TestClient(app) as client:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    admin_role = db.scalar(select(Role).where(Role.name == "Admin"))
                    own_grant = db.scalar(select(Grant).where(Grant.user_id == 1))
                    filed_jobs = list(db.scalars(select(Job).where(Job.stage == "Filed").order_by(Job.id).limit(2)))
                if not admin_role or not own_grant:
                    print("ERROR: Seeded Admin role or grant missing; cannot run security checks.")
                    return 2
                if len(filed_jobs) < 2:
                    print("ERROR: Need at least two Filed jobs for isolated exception checks.")
                    return 2
                filed_a, filed_b = (j.id for j in filed_jobs)
                print("Running security checks (all writes will be rolled back)...\n")

                expect_http(client, "Admin cannot grant themselves a role", "POST", "/api/grants", 1,
                            {"user_id": 1, "role_id": admin_role.id}, 403)
                expect_http(client, "Ordinary staff cannot grant roles", "POST", "/api/grants", 4,
                            {"user_id": 10, "role_id": admin_role.id}, 403)
                expect_http(client, "Admin cannot revoke own grants", "DELETE",
                            f"/api/grants/{own_grant.id}", 1, None, 403)
                expect_http(client, "Privileged new role rejected", "POST", "/api/roles", 1,
                            {"name": "SmokeTestPrivilegedRole", "actions": ["grant.manage"]}, 403)
                expect_http(client, "Maker cannot reassign a job", "POST", "/api/jobs/21/reassign", 4,
                            {"owner_id": 10}, 403)
                expect_decision(client, "Parser cannot check a job", 20, "job.check", 11,
                                False, "SERVICE_RESTRICTED")
                expect_decision(client, "Absent employee is denied", 6, "job.prepare", 21,
                                False, "USER_ABSENT")
                expect_decision(client, "Client can view own client job", 19, "job.view", 11,
                                True, "MATCHED_GRANT")
                expect_decision(client, "Client cannot view another client job", 19, "job.view", 12,
                                False, "NO_MATCHING_GRANT")
                expect_http(client, "Staff cannot evaluate another user's access", "POST", "/api/authorize", 2,
                            {"user_id": 19, "action": "job.view", "job_id": 11}, 403)
                expect_http(client, "Admin can view system audit", "GET", "/api/audit", 1, None, 200)
                expect_http(client, "Ordinary staff cannot view system audit", "GET", "/api/audit", 4, None, 403)

                # Asha is both an exception requester and an approver, but must never approve her own request.
                requested = expect_http(client, "Admin can request valid exception", "POST",
                                        f"/api/jobs/{filed_a}/exception-request", 1,
                                        {"action": "cancel", "justification": "Smoke test self approval restriction"}, 200)
                if requested is not None and requested.status_code == 200:
                    expect_http(client, "Requester cannot approve their own exception", "POST",
                                f"/api/jobs/{filed_a}/exception-approve", 1,
                                {"approve": True, "justification": "Smoke test approval restriction"}, 403)

                # A Supervisor can request an exception; Asha can independently approve it.
                requested = expect_http(client, "Supervisor can request valid exception", "POST",
                                        f"/api/jobs/{filed_b}/exception-request", 8,
                                        {"action": "cancel", "justification": "Smoke test independent approval"}, 200)
                if requested is not None and requested.status_code == 200:
                    approved = expect_http(client, "Independent admin approves exception", "POST",
                                           f"/api/jobs/{filed_b}/exception-approve", 1,
                                           {"approve": True, "justification": "Smoke test independent approval"}, 200)
                    if approved is not None and approved.status_code == 200:
                        record("Approved exception changes stage", approved.json().get("stage") == "Cancelled",
                               f"stage={approved.json().get('stage')}")

        finally:
            app.dependency_overrides.pop(db_session, None)
            outer.rollback()
            print("\nRolled back all smoke-test database writes.")
    engine.dispose()
    passing = sum(ok for _, ok, _ in results)
    print(f"\nSUMMARY: {passing}/{len(results)} checks passed")
    return 0 if passing == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
