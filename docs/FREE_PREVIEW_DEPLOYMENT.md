# Free preview deployment

The root `render.yaml` deploys Workspace as one free Render web service. Nginx
serves the React build and proxies API, GraphQL, and WebSocket traffic to the
FastAPI process in the same container, so authentication remains same-origin.

This configuration is for evaluation only:

- Render free services sleep after periods of inactivity and can take about a
  minute to wake.
- SQLite, uploaded files, and changes made in the demo are ephemeral. They are
  recreated from synthetic demo data after a restart or redeploy.
- Email is written to application logs.
- The local reasoning model is not hosted. Deterministic workspace actions and
  limited-mode assistant behavior remain available.
- Production requires managed PostgreSQL, Redis, S3-compatible storage,
  attachment scanning, SMTP, TURN/SFU, and dedicated model infrastructure.

## Demo sign-in

Every synthetic account uses `WorkspaceDemo2026!`. Available account email
addresses and roles are listed in `docs/DEMO_PLAYGROUND.md`.

## Deploy

1. In Render, select **New → Blueprint**.
2. Connect `iamakshayj/workspace` and select the `main` branch.
3. Review the single free web service and apply the Blueprint.
4. Wait for `/health` to pass, then open the generated `onrender.com` URL.

No paid resources or custom domain are required for this preview.
