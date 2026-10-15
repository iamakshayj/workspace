# Confluence-style knowledge capability map

This document treats “Confluence features” as product capability families rather than claiming compatibility with every Atlassian edition, marketplace app, or historical feature. `Delivered` means the workflow is available in this repository. `Platform` means the capability is supplied by another Workspace module and is connected through the shared navigation, identity, search, notification, or work-graph layer. `Integration` identifies vendor-specific work that requires a separate service or licensed identity/integration provider.

## Content creation and authoring

| Capability | Status | Workspace implementation |
| --- | --- | --- |
| Pages and drafts | Delivered | Versioned pages with draft, published, and archived states |
| Rich structured content | Delivered | Headings, emphasis, links, quotes, lists, tasks, tables, code blocks, panels, and expandable sections |
| Live preview and page outline | Delivered | Write/preview modes and heading-based in-page navigation |
| Templates | Delivered | Blank, brief, SOP, meeting, decision, policy, requirements, retrospective, incident, how-to, and team-home templates |
| Draft recovery | Delivered | Debounced browser recovery scoped to page revision |
| Custom page title, summary, icon, and labels | Delivered | Persisted metadata, searchable page list, and label filters |
| Mentions and internal page links | Delivered | `@username` rendering/notifications and `[[doc:UUID]]` links |
| Diagrams, whiteboards, smart tables, and AI assistance | Platform | Existing Workflow, smart-table, and Workspace Assistant modules |
| Full WYSIWYG collaborative editor | Integration | A production CRDT editor such as Yjs/Tiptap or ProseMirror collaboration remains a dedicated phase |
| Managed page attachments and Office/PDF previews | Integration | Reuse the platform object-storage, scanning, preview, and file-permission services in a follow-up phase |

## Organization and discovery

| Capability | Status | Workspace implementation |
| --- | --- | --- |
| Workspace and restricted spaces | Delivered | Tenant-scoped spaces with owner/admin management |
| Hierarchical page tree | Delivered | Same-space parents, stable sibling ordering, nested navigation, and circular-tree prevention |
| Move and copy pages | Delivered | Move through page settings; copy from page actions |
| Favorites, recents, labels, filters, and archive views | Delivered | Personal favorites plus server-backed metadata/filtering |
| Keyword search with permissions | Delivered | Title, summary, and body search filtered by document and space access |
| Backlinks and related pages | Delivered | Outbound and inbound page relationships are synchronized on save |
| Enterprise hybrid search and work graph | Platform | Shared search and graph services connect knowledge with work, meetings, risks, and decisions |
| Blogs/news feeds and content databases | Integration | Not represented as separate Confluence-compatible object types |

## Collaboration

| Capability | Status | Workspace implementation |
| --- | --- | --- |
| Page comments | Delivered | Durable permission-checked comments |
| Threaded replies | Delivered | Reply context, persisted parent relationships, and thread indentation |
| Mentions and notifications | Delivered | Mention notifications use the shared real-time inbox |
| Follow/watch pages | Delivered | Per-user following and update/comment notifications |
| Resolve/reopen conversations | Delivered | Authors and editors can manage comment state |
| Page sharing and viewer/commenter/editor roles | Delivered | Explicit page access plus inherited workspace visibility |
| Simultaneous cursor-level page editing | Integration | Document changes are version-safe, but rich-text CRDT presence is not claimed |
| Reactions and inline text-selection comments | Integration | Page-level threads are delivered; selection anchors and comment reactions are separate editor work |

## Governance and lifecycle

| Capability | Status | Workspace implementation |
| --- | --- | --- |
| Optimistic concurrency | Delivered | Expected revisions prevent silent overwrites |
| Immutable version history | Delivered | Every save creates a revision with actor, time, and change summary |
| Compare and restore versions | Delivered | Side-by-side historical preview and permission-checked restore |
| Page status and archive/restore | Delivered | Lifecycle actions retain links and history |
| Ownership and classification | Delivered | Owner plus public/internal/confidential/restricted classification |
| Review and expiry | Delivered | Review/expiry dates, overdue state, and home counters |
| Space and page permissions | Delivered | Workspace/restricted visibility, space roles, and document roles |
| Audit history, retention, entity isolation, and data residency | Platform | Existing enterprise governance and audit services |
| Public anonymous links | Integration | Intentionally excluded until token revocation, expiry, watermarking, and download controls are defined |

## Content operations and administration

| Capability | Status | Workspace implementation |
| --- | --- | --- |
| Space settings | Delivered | Name, description, and visibility management for owners/admins |
| Content health dashboard | Delivered | Total, published, draft, review-due, and expired indicators |
| Export and print | Delivered | Markdown download and browser print/PDF output |
| Responsive and dark/light themes | Platform | Shared responsive shell and user theme preference |
| Search, notifications, people, calendar, chat, meetings, and tasks | Platform | Shared Workspace modules remain accessible from persistent top navigation |
| Atlassian import/export fidelity | Integration | Space XML, legacy storage-format macros, and permission mapping need an isolated importer |
| Marketplace, Forge/Connect APIs, and Atlassian smart links | Integration | Vendor ecosystem compatibility is outside the native knowledge implementation |
| SAML/SCIM and managed accounts | Integration | Enterprise identity-provider provisioning is a deployment integration |
| Data Center clustering and Atlassian mobile clients | Integration | The product uses its own deployment and responsive web architecture |

## Acceptance boundary

The delivered scope is a complete native knowledge workflow: organize pages, author structured content, collaborate, govern access and lifecycle, discover relationships, compare history, and export. Vendor-specific compatibility and infrastructure are intentionally listed as integrations so product demos and procurement material do not imply unsupported Atlassian parity.
