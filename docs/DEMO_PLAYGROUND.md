# Enterprise demo playground

The local database contains an isolated **Acme Enterprise Playground** workspace designed for demonstrations, QA, role testing, and product exploration.

> These credentials are local demo data only. Never use this shared password in a deployed environment.

## Login

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) and use any account below.

Password for every account: `WorkspaceDemo2026!`

| Account | Role | Job scenario |
|---|---|---|
| `avery.admin@acme.demo` | Admin | Executive portfolio, dashboards, approvals, audit, and organization management |
| `jordan.platform@acme.demo` | Admin | Platform configuration, security, restricted projects, and knowledge governance |
| `priya.program@acme.demo` | Basic | Cross-project planning, active sprint, risks, meetings, and saved views |
| `marcus.product@acme.demo` | Basic | Product ownership, onboarding project, roadmap, and discovery work |
| `elena.engineering@acme.demo` | Basic | Engineering management, capacity, architecture, and mobile delivery |
| `sam.developer@acme.demo` | Basic | Assigned implementation work, comments, subtasks, and team chat |
| `nina.qa@acme.demo` | Basic | QA queues, defects, evidence, release gates, and approvals |
| `leo.design@acme.demo` | Basic | Product design stories, collaboration, and workflow review |
| `mia.analyst@acme.demo` | Basic | Business analysis, BPMN workflows, documentation, and reporting |
| `omar.operations@acme.demo` | Basic | Operations planning, store rollout, dependencies, and service metrics |
| `sofia.sales@acme.demo` | Basic | Revenue operations project, CRM handoffs, and forecasting work |
| `ethan.finance@acme.demo` | Basic | Restricted ERP project, budgets, controls, and procurement files |
| `grace.people@acme.demo` | Basic | Restricted workforce plan, hiring work, policy documents, and calendar |
| `diego.support@acme.demo` | Basic | Support workflows, self-hosted assistant project, incidents, and knowledge |
| `riley.auditor@acme.demo` | Guest | Restricted guest experience with explicit access to audit/onboarding content |

## Dataset coverage

- 15 users: 2 admins, 12 basic members, and 1 guest
- 10 organization units with nested business units, departments, teams, managers, skills, capacity, and timezones
- 8 projects spanning Product, Engineering, Security, Revenue, Finance, Support, People, and Operations
- 144 work items evenly distributed across backlog, selected, active, QA, review, blocked, and done states
- Initiatives, epics, stories, tasks, subtasks, defects, spikes, approvals, deliverables, milestones, improvements, and technical debt
- 4 sprints, 4 releases, baselines and planning scenarios
- 24 project risks, 16 project decisions, cross-project relationships, work blockers, and node planning bindings
- 30 calendar events with attendees, RSVP states, reminders, recurrence, external guests, agendas, notes, actions, transcripts, and recording references
- 24 linked and revisioned knowledge documents across public and restricted spaces
- 6 communication channels/groups, 108 channel messages, direct messages, reactions, pins, mentions, and attachments
- 90 notifications, saved board/report views, dashboards, governed files, approvals, and tamper-evident audit events

## Suggested walkthroughs

1. Sign in as Avery to use **Operations**, inspect all projects, verify the audit chain, edit organization data, and compare executive dashboards.
2. Sign in as Priya to open **Work**, select the saved active-sprint board, switch swimlanes, inspect threaded work comments, and explore the roadmap.
3. Sign in as Nina to examine QA stages, defects, approval requests, evidence files, meetings, and release readiness.
4. Sign in as Sam to see an individual contributor’s assignments, comments, calendar, channels, and editable work.
5. Sign in as Riley to validate guest isolation. The guest cannot open workspace Operations and only sees explicitly shared projects and restricted audit documents.

## Recreate or refresh

The generator is idempotent. If the playground already exists, it refreshes the known account passwords without duplicating records:

```bash
PYTHONPATH=. .venv/bin/python scripts/seed_enterprise_demo.py
```

The script refuses to execute when the backend environment is set to production.
