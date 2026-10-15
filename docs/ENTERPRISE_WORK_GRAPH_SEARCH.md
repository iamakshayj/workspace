# Enterprise Work Graph and Search

Workspace now uses one canonical relationship store for projects, work items, sprints, releases, meetings, documents, files, decisions, risks, approvals, people, teams, and custom objects.

## Work Graph

The API is available under `/api/v1/work-graph`.

- `GET /objects/{type}/{id}` resolves one object after checking access.
- `GET /objects/{type}/{id}/related?depth=1&direction=both` traverses incoming and outgoing links. Depth is limited to five and every discovered node is permission-checked before it or its edge is returned.
- `GET /objects/{type}/{id}/history` combines relationship history and object audit history.
- `POST /relationships`, `PUT /relationships/{id}`, and `DELETE /relationships/{id}` manage canonical links. Editors can link objects they are allowed to edit; guests cannot mutate links.

Dependency relationships reject circular paths. Relationship creation, changes, and deletion are preserved in `object_relationship_history`, including the actor and metadata snapshot.

The Project Details dialog includes a **Related items** tab. Search previews use the same service and can inspect up to three hops without leaving search.

## Enterprise Search

Open Search from any top navigation bar or press `Cmd/Ctrl + K`. The search surface covers projects, work items, documents, meetings, decisions, risks, releases, sprints, and files.

Search modes:

- **Keyword** prioritizes exact titles, keys, metadata, and body matches.
- **Semantic** uses a deterministic local concept projection with synonym expansion. It sends no content to an external provider.
- **Hybrid** combines keyword precision with local semantic recall.

All modes apply the canonical access scope before ranking or building facets. Restricted project content, documents, files, and guest-only meeting access cannot appear in result counts, snippets, previews, or graph traversal.

The API is available under `/api/v1/search`:

- `GET /search` supports `q`, `mode`, `types`, `statuses`, `project_id`, `owner_id`, date boundaries, offset, and limit.
- `GET/POST/PUT/DELETE /search/saved` manages private or shared reusable searches.
- `GET /search/recent` and `DELETE /search/recent` manage the current user's bounded search history.

Search responses include permission-filtered type, status, and project facets plus preview snippets and application routes.

## Scale path

Permission grants are preloaded once per request to avoid per-result access queries. Searches cap each object family at 10,000 recent active records, while API pagination bounds response sizes. For deployments that outgrow that corpus, keep these API contracts and move document retrieval to PostgreSQL full-text indexes plus a self-hosted vector index; the UI and permission layer do not need to change.
