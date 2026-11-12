# NFPL Access Control Service — Technical Design

**Scope:** assignment demonstration | **Stack:** React/TypeScript → FastAPI → SQLAlchemy → PostgreSQL 17
**Review date:** 12 November 2026 | **Expected length:** approximately 3–4 pages in standard document layout

## Architecture and request path

```text
React dashboard / Decision Explorer
    │ JSON over HTTP; X-Actor-Id (DEMO ONLY)
    ▼
FastAPI routes → identity dependency → authorization decision(db, user, action, job)
    │                                    │
    │                                    ├── user status / kind
    │                                    ├── stage and separation-of-duties constraints
    │                                    └── active permission + scoped grant match
    ▼
SQLAlchemy Session → PostgreSQL (users, roles, permissions, grants, jobs, audit)
```

Read APIs filter by actor-visible scope; My Work first narrows candidates with SQL, then applies the same decision engine used for mutations. Sensitive endpoints re-evaluate permissions on execution rather than trusting prior browser decisions. The UI’s **Acting as** selector supplies a deliberately insecure demonstration identity and must not be mistaken for authentication.


## Model

A `User` is staff, client, or service identity. `Role` has one or more `Permission` actions. `Grant` attaches a role to a user with optional client, branch, direction and mode constraints. NULL in a grant scope means unrestricted. `Job` holds immutable business dimensions for this MVP and mutable stage, owner, maker/checker identities and version. `Audit` stores append-only activity events and decision checks. The central `decision` function is used by endpoints and inbox logic. Explicit deny rules override matched grants. Missing/unknown access is denied.

## Workflow

Confirmed → Prepared (`job.prepare`) → Checked (`job.check`) → Filed (`job.file`). The maker cannot check the same job, and the checker cannot file it. Filed jobs have no ordinary edit action. A supervisor/admin can request a filed cancellation or a filed/cancelled reopening, requiring a different privileged approver and written reasons. Reopening returns to Confirmed and clears maker/checker fields while preserving historical events.

## Answers to the fourteen questions

1. **Visibility vs action:** `job.view` is separately granted. Client users are client-scoped and read-only; Maker/Checker grants include scoped viewing. Visible does not imply writable.
2. **Overlapping narrow roles:** Multiple additive grants express Maker globally + Checker for two clients, or Checker for a single client, branch and direction. No combinatorial role explosion.
3. **Self-approval:** Always deny checking one's own prepared job, even when the role matches. Likewise checker cannot file their own checked job.
4. **Absent owner:** Absence blocks action, but not viewing. Authorized supervisor can reassign to an active, present user with visibility, with an audit event.
5. **Changing responsibilities:** Revocation is checked on each request. In-flight work is retained, but no grandfathering; a new qualified person completes the next step.
6. **Filed cancel/reopen:** Separate request and approval by different privileged actors with reasons, job-version guard, and audit. This is stricter than ordinary stage changes.
7. **Client employee:** ClientViewer with an explicit client scope; read-only and no cross-client access.
8. **Admin fixes and self-escalation:** Admin may reassign/request/approve exceptions but cannot grant/revoke their own roles. Role creation is restricted to nonprivileged actions. Production would add independent approval and break-glass controls.
9. **Overnight parser:** Dedicated service identity with create/update permissions, restricted to early stages. It cannot approve, file or modify a filed job.
10. **Why she can and he cannot:** Evaluate identical action/job for two users; return reason code, explanation, matched role and grant ID where allowed.
11. **Who could have changed it on the 3rd:** Audit captures actual actions and permission changes, but **complete historical eligibility reconstruction is not implemented**. A production solution needs immutable grant validity intervals, historic user status, job snapshots, policy versions and as-of evaluation.
12. **New role:** Role and permissions are stored as data; an admin can create a nonprivileged role using a controlled allowlist. New action names or privileged actions still require engineering/security review.
13. **Waiting-for-me consistency:** SQL prefilters on stage and grant scope, then calls the same decision function used for execution. This trades a small amount of CPU for consistent membership.
14. **Uncertainty:** Fail closed with an explicit denial reason; never guess or silently permit.

## Additional question: what if permission changes between a check and execution?

The API always rechecks at execution, rather than trusting a previous decision response. The current MVP does not provide serializable isolation or explicit row locking, so a narrow concurrency race remains. Production would lock relevant job/grant records or use a policy-version validation strategy.

## Validation evidence

The local demonstration was checked against a PostgreSQL database containing **5 branches, 10 clients, 20 users, 8 roles, 30 grants and 320 jobs**. The automated backend suite passed **10/10** tests, and an additional **17/17** security smoke checks passed with smoke-test writes rolled back. A React production build passed, and a browser workflow confirmed database persistence plus maker/checker separation. These results demonstrate selected functional behaviors, not exhaustive security verification or measured 200k-job performance.

## Scale and indexes

The job stage/scope composite index supports common worklist predicates; grant user/role/scope indexes narrow candidate grants. List endpoints cap page sizes. The inbox uses indexed stage/scope filtering and exact authorization on candidates. Real performance needs `EXPLAIN ANALYZE` against the generated 200k-job dataset, including worst-case broad grants.

## Security and operational trade-offs

The application is a **local demonstration**, not a hardened deployment. It uses a user-selected `X-Actor-Id` header so evaluators can easily switch personas; this is impersonation and is unsafe on a public network. Replace it with OIDC/JWT verification, authenticated service identities, rate limiting, HTTPS, restricted CORS, database migration workflows, stricter request validation and audit retention before deployment. Current `Audit` is append-only by application convention, not tamper-evident storage. Audit decisions are logged when the explicit authorize endpoint is used; not every internal authorization check is individually persisted. A production implementation should emit structured decisions for every sensitive action, without leaking private information.
