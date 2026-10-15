import 'reactflow/dist/style.css';
import './App.css';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background, ConnectionMode, Controls, MiniMap, MarkerType, addEdge, applyEdgeChanges, applyNodeChanges,
} from 'reactflow';
import { toPng } from 'html-to-image';
import { generateFlowchart, getHealth, getProject, saveProject, searchProjects } from './flowchartService';
import { AuthProvider, useAuth } from './AuthProvider';
import FlowNode from './FlowNode';
import ProjectDetailsDialog from './ProjectDetailsDialog';
import ProjectExportMenu from './ProjectExportMenu';
import { ThemeProvider, useTheme } from './ThemeProvider';
import { CollaborationClient } from './collaborationService';
import { CollaborationPanel, PresenceStack, RemoteCursors } from './CollaborationControls';
import { getCommunicationOverview } from './communicationService';
import DiagramLibrary from './DiagramLibrary';
import NodeAttachments from './NodeAttachments';
import { deleteAttachment, listAttachments, uploadAttachment } from './attachmentService';
import ProcessIntelligencePanel from './ProcessIntelligencePanel';
import { EMPTY_PROCESS_ANALYTICS, getProcessAnalytics } from './processIntelligenceService';
import WorkManagement from './WorkManagement';
import NodePlanningPanel from './NodePlanningPanel';
import { getProjectPlanning } from './workService';
import CalendarManagement from './CalendarManagement';
import HomeDashboard from './HomeDashboard';
import WorkspaceTopNav from './WorkspaceTopNav';
import WorkflowSheet from './WorkflowSheet';
import KnowledgeManagement from './KnowledgeManagement';
import EnterpriseManagement from './EnterpriseManagement';
import PlatformAdmin from './PlatformAdmin';
import ServiceDesk from './ServiceDesk';
import GuestPortal from './GuestPortal';
import { recordOperationalEvent } from './platformService';

const NODE_COLORS = {
  start: '#DDF8E8', end: '#FFE4E7', decision: '#FFF1C7', document: '#E3EEFF',
  external_system: '#EDE5FF', wait: '#E9EDF3', subprocess: '#DFF5F3', process: '#FFFFFF',
  swimlane: '#F6F8FB',
};
const NODE_TYPES = { flowNode: FlowNode };
const COLOR_PALETTE = [
  { name: 'White', value: '#FFFFFF' },
  { name: 'Mint', value: '#DDF8E8' },
  { name: 'Sky', value: '#DDEEFF' },
  { name: 'Lavender', value: '#EDE5FF' },
  { name: 'Sunshine', value: '#FFF1C7' },
  { name: 'Peach', value: '#FFE3D2' },
  { name: 'Rose', value: '#FFE0E6' },
  { name: 'Slate', value: '#E9EDF3' },
];
const EMPTY_PROJECT_PROFILE = {
  key: '', sponsor_id: null, department: '', team: '', program: '', priority: 'medium',
  health: 'unknown', start_date: null, target_date: null, progress: null,
  classification: 'internal', tags: [], template: 'blank',
};

function routeFromPath() {
  const match = window.location.pathname.match(/^\/projects\/([^/]+)$/);
  if (match) return { name: 'editor', projectId: match[1] };
  if (window.location.pathname === '/editor') return { name: 'editor', projectId: null };
  if (window.location.pathname === '/work') return { name: 'work', projectId: null };
  if (window.location.pathname === '/calendar') return { name: 'calendar', projectId: null };
  if (window.location.pathname === '/knowledge') return { name: 'knowledge', projectId: null };
  if (window.location.pathname === '/service') return { name: 'service', projectId: null };
  if (window.location.pathname === '/operations') return { name: 'operations', projectId: null };
  if (window.location.pathname === '/admin') return { name: 'admin', projectId: null };
  if (['/workflows', '/flowcharts'].includes(window.location.pathname)) return { name: 'workflows', projectId: null };
  return { name: 'dashboard', projectId: null };
}

function formatUpdatedAt(value) {
  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}

function countLabel(count, singular) {
  return `${count} ${singular}${count === 1 ? '' : 's'}`;
}

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function safeClientError(value) {
  return String(value || 'Unknown client error')
    .replace(/(bearer|password|secret|token|api[_ -]?key)\s*[:=]?\s*[^\s,;]+/gi, '$1=[redacted]')
    .slice(0, 900);
}

function errorFingerprint(message, source = '') {
  let hash = 2166136261;
  const input = `${source}:${message}`;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `client-${(hash >>> 0).toString(16)}`;
}

function AiSparkIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 2.75c.45 4.7 2.65 6.9 7.25 7.25-4.6.35-6.8 2.55-7.25 7.25-.45-4.7-2.65-6.9-7.25-7.25C9.35 9.65 11.55 7.45 12 2.75Z" />
    <path d="M18.5 15.25c.2 2.1 1.2 3.1 3.25 3.25-2.05.15-3.05 1.15-3.25 3.25-.2-2.1-1.2-3.1-3.25-3.25 2.05-.15 3.05-1.15 3.25-3.25Z" />
  </svg>;
}

function ClearCanvasDialog({ open, nodeCount, edgeCount, onCancel, onConfirm }) {
  const cancelRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const previousFocus = document.activeElement;
    cancelRef.current?.focus();
    const closeOnEscape = (event) => { if (event.key === 'Escape') onCancel(); };
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      previousFocus?.focus?.();
    };
  }, [open, onCancel]);

  if (!open) return null;
  return <div className="clear-canvas-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onCancel();
  }}>
    <section className="clear-canvas-dialog" role="alertdialog" aria-modal="true"
      aria-labelledby="clear-canvas-title" aria-describedby="clear-canvas-description">
      <span className="clear-canvas-warning" aria-hidden="true">!</span>
      <h2 id="clear-canvas-title">Clear this canvas?</h2>
      <p id="clear-canvas-description">This removes every step and connection from the canvas. You can undo the action immediately afterward.</p>
      <div className="clear-canvas-summary">
        <span><strong>{nodeCount}</strong> {nodeCount === 1 ? 'step' : 'steps'}</span>
        <span><strong>{edgeCount}</strong> {edgeCount === 1 ? 'connection' : 'connections'}</span>
      </div>
      <footer>
        <button ref={cancelRef} className="button secondary" onClick={onCancel}>Cancel</button>
        <button className="button destructive" onClick={onConfirm}>Clear canvas</button>
      </footer>
    </section>
  </div>;
}

export function readStoredArray(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export function collaborativeDocument(document) {
  return {
    title: document.title,
    source_text: document.source_text,
    graph: document.graph,
  };
}

function connectionSides(source, target) {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  if (Math.abs(dx) > Math.abs(dy)) {
    return dx >= 0
      ? { sourceHandle: 'right', targetHandle: 'left' }
      : { sourceHandle: 'left', targetHandle: 'right' };
  }
  return dy >= 0
    ? { sourceHandle: 'bottom', targetHandle: 'top' }
    : { sourceHandle: 'top', targetHandle: 'bottom' };
}

function toReactFlow(graph) {
  const positions = Object.fromEntries(graph.nodes.map((node) => [node.id, { x: node.x, y: node.y }]));
  return {
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      type: 'flowNode',
      position: { x: node.x, y: node.y },
      style: { width: node.width || 180, height: node.height || 76 },
      zIndex: node.type === 'swimlane' ? -1 : 0,
      data: {
        label: node.label, type: node.type, owner: node.owner, description: node.description,
        color: node.color, shape: node.shape || 'rounded', symbol: node.symbol || null,
        backup_owner: node.backup_owner || '', system: node.system || '', vendor: node.vendor || '',
        control_id: node.control_id || '', policy_reference: node.policy_reference || '',
        evidence_requirement: node.evidence_requirement || '', segregation_rule: node.segregation_rule || '',
        risk_level: node.risk_level || 'none', data_classification: node.data_classification || 'internal',
        sla_minutes: node.sla_minutes || '', review_date: node.review_date || '',
        required: Boolean(node.required), layer: node.layer || 'Default', parent_id: node.parent_id || '',
      },
    })),
    edges: graph.edges.map((edge, index) => ({
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source, target: edge.target, label: edge.label || undefined,
      ...connectionSides(positions[edge.source], positions[edge.target]),
      animated: edge.is_loop,
      bidirectional: edge.bidirectional,
      markerStart: edge.bidirectional ? { type: MarkerType.ArrowClosed, width: 18, height: 18 } : undefined,
      markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
      style: { stroke: edge.is_loop ? '#8B5CF6' : '#64748B', strokeWidth: 1.5 },
      labelStyle: { fill: '#334155', fontWeight: 600 },
    })),
  };
}

function graphHistorySnapshot(state) {
  return JSON.parse(JSON.stringify({
    nodes: state.nodes,
    edges: state.edges,
    title: state.title,
    warnings: state.warnings,
    questions: state.questions,
    sourceText: state.sourceText,
  }));
}

function NodeSizeInput({ dimension, value, disabled, onCommit }) {
  const [draft, setDraft] = useState(String(Math.round(value)));
  const focusedRef = useRef(false);
  const minimum = dimension === 'width' ? 80 : 44;
  const maximum = dimension === 'width' ? 720 : 520;

  useEffect(() => {
    if (!focusedRef.current) setDraft(String(Math.round(value)));
  }, [value]);

  const commit = (rawValue) => {
    const numericValue = Number(rawValue);
    const normalized = Math.max(minimum, Math.min(maximum, Number.isFinite(numericValue)
      ? numericValue
      : minimum));
    onCommit(dimension, normalized);
    return normalized;
  };

  return <input aria-label={`Node ${dimension}`} type="number" min={minimum} max={maximum}
    disabled={disabled} value={draft}
    onFocus={() => { focusedRef.current = true; }}
    onChange={(event) => {
      const next = event.target.value;
      setDraft(next);
      if (next !== '' && Number.isFinite(Number(next))) onCommit(dimension, Number(next));
    }}
    onBlur={() => {
      focusedRef.current = false;
      setDraft(String(Math.round(commit(draft))));
    }}
    onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} />;
}

function FlowForgeWorkspace() {
  const { user } = useAuth();
  const { resolvedTheme } = useTheme();
  const isAdmin = user.role === 'admin';
  const workspaceCanManage = user.role === 'admin';
  const [projectAccess, setProjectAccess] = useState(isAdmin ? 'admin' : null);
  const canManage = workspaceCanManage || ['owner', 'editor'].includes(projectAccess);
  const canComment = canManage || ['commenter', 'approver'].includes(projectAccess);
  const storagePrefix = `flowforge:${user.id}`;
  const [workflowView, setWorkflowView] = useState(() => {
    const stored = localStorage.getItem(`${storagePrefix}:workflow-view`);
    return ['diagram', 'sheet', 'split'].includes(stored) ? stored : 'diagram';
  });
  const [nodes, setNodes] = useState(() => readStoredArray(`${storagePrefix}:nodes`).map(
    (node) => ({ ...node, type: 'flowNode' })
  ));
  const [edges, setEdges] = useState(() => readStoredArray(`${storagePrefix}:edges`));
  const [title, setTitle] = useState(() => localStorage.getItem(`${storagePrefix}:title`) || 'Untitled process');
  const [projectDescription, setProjectDescription] = useState('');
  const [projectStatus, setProjectStatus] = useState('active');
  const [projectProfile, setProjectProfile] = useState(EMPTY_PROJECT_PROFILE);
  const [projectApprovalStatus, setProjectApprovalStatus] = useState('draft');
  const [projectOwnerId, setProjectOwnerId] = useState(user.id);
  const [projectCollaboratorIds, setProjectCollaboratorIds] = useState([user.id]);
  const [projectDetailsOpen, setProjectDetailsOpen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState([]);
  const [selectedEdgeId, setSelectedEdgeId] = useState(null);
  const [prompt, setPrompt] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState('');
  const [warnings, setWarnings] = useState([]);
  const [questions, setQuestions] = useState([]);
  const [health, setHealth] = useState({ api: 'checking', model: false });
  const [projectId, setProjectId] = useState(() => routeFromPath().projectId);
  const [documentRevision, setDocumentRevision] = useState(0);
  const [saveConflict, setSaveConflict] = useState(null);
  const [sourceText, setSourceText] = useState('');
  const [saveState, setSaveState] = useState('idle');
  const [route, setRoute] = useState(routeFromPath);
  const [projects, setProjects] = useState([]);
  const [projectsState, setProjectsState] = useState('loading');
  const [projectSearch, setProjectSearch] = useState('');
  const [projectNextCursor, setProjectNextCursor] = useState(null);
  const [projectTotalCount, setProjectTotalCount] = useState(0);
  const [projectsLoadingMore, setProjectsLoadingMore] = useState(false);
  const [collaborationStatus, setCollaborationStatus] = useState('offline');
  const [collaborators, setCollaborators] = useState([]);
  const [remoteCursors, setRemoteCursors] = useState({});
  const [projectTasks, setProjectTasks] = useState([]);
  const [projectDeliverables, setProjectDeliverables] = useState([]);
  const [projectNotes, setProjectNotes] = useState([]);
  const [communicationContacts, setCommunicationContacts] = useState([]);
  const [collaborationOpen, setCollaborationOpen] = useState(false);
  const [collaborationReady, setCollaborationReady] = useState(false);
  const [collaborationError, setCollaborationError] = useState('');
  const [diagramLibraryOpen, setDiagramLibraryOpen] = useState(false);
  const [aiPanelOpen, setAiPanelOpen] = useState(false);
  const [clearCanvasOpen, setClearCanvasOpen] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [intelligenceOpen, setIntelligenceOpen] = useState(false);
  const [processAnalytics, setProcessAnalytics] = useState(EMPTY_PROCESS_ANALYTICS);
  const [projectPlanning, setProjectPlanning] = useState(null);
  const [activeLayer, setActiveLayer] = useState('All');
  const collaborationRef = useRef(null);
  const lastDocumentSignatureRef = useRef('');
  const saveInProgressRef = useRef(false);
  const cursorSentAtRef = useRef(0);
  const historyRef = useRef([]);
  const graphStateRef = useRef(null);
  const nodeDragSnapshotRef = useRef(null);
  const reactFlowRef = useRef(null);
  const [historyDepth, setHistoryDepth] = useState(0);
  const [presentationMode, setPresentationMode] = useState(false);
  const [focusSeconds, setFocusSeconds] = useState(0);

  useEffect(() => {
    const recentlyReported = new Map();
    const report = (raw, source) => {
      const message = safeClientError(raw);
      const fingerprint = errorFingerprint(message, source);
      const now = Date.now();
      if (now - (recentlyReported.get(fingerprint) || 0) < 60_000) return;
      recentlyReported.set(fingerprint, now);
      recordOperationalEvent({
        service: 'web-client', severity: 'error', fingerprint, message,
        context: { source, path: window.location.pathname, browser_online: navigator.onLine },
      }).catch(() => {});
    };
    const onError = (event) => report(event.error?.message || event.message, 'window.error');
    const onRejection = (event) => report(event.reason?.message || event.reason, 'unhandledrejection');
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
    };
  }, []);

  graphStateRef.current = { nodes, edges, title, warnings, questions, sourceText };

  useEffect(() => {
    if (!focusSeconds) return undefined;
    const timer = window.setInterval(() => setFocusSeconds((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [focusSeconds > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const pushHistory = useCallback((snapshot, group = null, coalesceMs = 750) => {
    if (!canManage || !snapshot) return;
    const signature = JSON.stringify(snapshot);
    const previous = historyRef.current.at(-1);
    if (previous?.signature === signature) return;
    const now = Date.now();
    if (group && previous?.group === group && now - previous.createdAt < coalesceMs) {
      previous.createdAt = now;
      return;
    }
    historyRef.current = [...historyRef.current, {
      snapshot, signature, group, createdAt: now,
    }].slice(-60);
    setHistoryDepth(historyRef.current.length);
  }, [canManage]);

  const recordHistory = useCallback((group = null, coalesceMs = 750) => {
    pushHistory(graphHistorySnapshot(graphStateRef.current), group, coalesceMs);
  }, [pushHistory]);

  const resetHistory = useCallback(() => {
    historyRef.current = [];
    nodeDragSnapshotRef.current = null;
    setHistoryDepth(0);
  }, []);

  const undo = useCallback(() => {
    if (!canManage || historyRef.current.length === 0) return;
    const entry = historyRef.current.at(-1);
    historyRef.current = historyRef.current.slice(0, -1);
    nodeDragSnapshotRef.current = null;
    setNodes(entry.snapshot.nodes);
    setEdges(entry.snapshot.edges);
    setTitle(entry.snapshot.title);
    setWarnings(entry.snapshot.warnings);
    setQuestions(entry.snapshot.questions);
    setSourceText(entry.snapshot.sourceText);
    setSelectedNodeId(null);
    setSelectedNodeIds([]);
    setSelectedEdgeId(null);
    setHistoryDepth(historyRef.current.length);
  }, [canManage]);

  useEffect(() => {
    getHealth()
      .then((result) => setHealth({ api: 'online', model: result.model_server_reachable, name: result.model }))
      .catch(() => setHealth({ api: 'offline', model: false }));
  }, []);
  useEffect(() => localStorage.setItem(`${storagePrefix}:nodes`, JSON.stringify(nodes)), [nodes, storagePrefix]);
  useEffect(() => localStorage.setItem(`${storagePrefix}:edges`, JSON.stringify(edges)), [edges, storagePrefix]);
  useEffect(() => localStorage.setItem(`${storagePrefix}:title`, title), [title, storagePrefix]);
  useEffect(() => localStorage.setItem(`${storagePrefix}:workflow-view`, workflowView), [storagePrefix, workflowView]);
  useEffect(() => {
    const onPopState = () => setRoute(routeFromPath());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    if (!['dashboard', 'workflows'].includes(route.name)) return;
    let active = true;
    setProjectsState('loading');
    setProjects([]);
    setProjectNextCursor(null);
    const isLibrary = route.name === 'workflows';
    const timer = window.setTimeout(() => {
      const request = () => searchProjects({ search: isLibrary ? projectSearch : '', first: isLibrary ? 24 : 6 });
      request()
        .then(async (initialPage) => {
          let page = initialPage;
          // The local API can briefly return an empty page while its workspace
          // seed is loading. Retry once before showing an empty dashboard.
          if (!isLibrary && page.total_count === 0) {
            await new Promise((resolve) => window.setTimeout(resolve, 300));
            if (!active) return;
            page = await request();
          }
          if (!active) return;
          setProjects(page.items);
          setProjectNextCursor(page.next_cursor);
          setProjectTotalCount(page.total_count);
          setProjectsState('ready');
        })
        .catch(() => { if (active) setProjectsState('error'); });
    }, isLibrary && projectSearch ? 250 : 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [projectSearch, route.name]);

  useEffect(() => {
    if (route.name !== 'editor') return;
    getCommunicationOverview()
      .then((result) => setCommunicationContacts(result.communication_contacts || []))
      .catch(() => setCommunicationContacts([]));
  }, [route.name, user.id]);

  useEffect(() => {
    if (route.name !== 'editor' || !projectId) {
      setAttachments([]);
      return undefined;
    }
    let active = true;
    listAttachments(projectId)
      .then((items) => { if (active) setAttachments(items); })
      .catch(() => { if (active) setAttachments([]); });
    return () => { active = false; };
  }, [projectId, route.name]);

  useEffect(() => {
    if (route.name !== 'editor' || !projectId) {
      setProcessAnalytics(EMPTY_PROCESS_ANALYTICS);
      return undefined;
    }
    let active = true;
    getProcessAnalytics(projectId)
      .then((result) => { if (active) setProcessAnalytics(result); })
      .catch(() => { if (active) setProcessAnalytics(EMPTY_PROCESS_ANALYTICS); });
    return () => { active = false; };
  }, [projectId, route.name]);

  useEffect(() => {
    if (route.name !== 'editor' || !projectId) {
      setProjectPlanning(null);
      return undefined;
    }
    let active = true;
    let loading = false;
    const loadPlanning = () => {
      if (loading) return;
      loading = true;
      getProjectPlanning(projectId)
        .then((result) => { if (active) setProjectPlanning(result); })
        .catch((requestError) => { if (active) setProjectPlanning({ error: requestError.message, nodes: {} }); })
        .finally(() => { loading = false; });
    };
    const refreshWhenFocused = () => { if (document.visibilityState === 'visible') loadPlanning(); };
    loadPlanning();
    window.addEventListener('focus', refreshWhenFocused);
    const interval = window.setInterval(refreshWhenFocused, 30_000);
    return () => { active = false; window.removeEventListener('focus', refreshWhenFocused); window.clearInterval(interval); };
  }, [projectId, route.name]);

  useEffect(() => {
    if (route.name !== 'editor' || !route.projectId) return;
    let active = true;
    setError('');
    setNodes([]); setEdges([]); setWarnings([]); setQuestions([]); setSourceText('');
    setSelectedNodeId(null); setSelectedEdgeId(null); resetHistory();
    getProject(route.projectId)
      .then((project) => {
        if (!active) return;
        const flow = toReactFlow(project.graph);
        setNodes(flow.nodes); setEdges(flow.edges); setTitle(project.title);
        const requestedNodeId = new URLSearchParams(window.location.search).get('node');
        if (requestedNodeId && flow.nodes.some((node) => node.id === requestedNodeId)) {
          setSelectedNodeId(requestedNodeId); setSelectedNodeIds([requestedNodeId]);
          window.setTimeout(() => reactFlowRef.current?.fitView({ nodes: [{ id: requestedNodeId }], padding: 1.4, duration: 220 }), 180);
        }
        setWarnings(project.graph.warnings || []); setQuestions(project.graph.questions || []);
        setSourceText(project.source_text || ''); setProjectId(project.id);
        setDocumentRevision(project.document_revision || 0); setSaveConflict(null);
        setProjectDescription(project.description || ''); setProjectStatus(project.status || 'active');
        setProjectProfile({ ...EMPTY_PROJECT_PROFILE, ...(project.profile || {}) });
        setProjectApprovalStatus(project.approval_status || 'draft');
        setProjectAccess(project.current_user_access || (isAdmin ? 'admin' : 'viewer'));
        setProjectOwnerId(project.owner?.id || user.id);
        setProjectCollaboratorIds(project.collaborators?.map((member) => member.id) || [project.owner?.id || user.id]);
        localStorage.setItem(`${storagePrefix}:projectId`, project.id);
      })
      .catch((requestError) => { if (active) setError(requestError.message); });
    return () => { active = false; };
  }, [isAdmin, resetHistory, route.name, route.projectId, storagePrefix, user.id]);

  useEffect(() => {
    if (!workspaceCanManage && route.name === 'editor' && !route.projectId) {
      window.history.replaceState({}, '', '/');
      setRoute({ name: 'dashboard', projectId: null });
    }
  }, [route.name, route.projectId, workspaceCanManage]);

  const selectedNode = useMemo(() => nodes.find((node) => node.id === selectedNodeId), [nodes, selectedNodeId]);
  const selectedEdge = useMemo(() => edges.find((edge) => edge.id === selectedEdgeId), [edges, selectedEdgeId]);
  const projectOwner = useMemo(() => [user, ...communicationContacts.map((contact) => contact.user || contact)]
    .find((member) => member.id === projectOwnerId) || user, [communicationContacts, projectOwnerId, user]);
  const attachmentCounts = useMemo(() => attachments.reduce((counts, attachment) => ({
    ...counts, [attachment.node_id]: (counts[attachment.node_id] || 0) + 1,
  }), {}), [attachments]);
  const nodeMetrics = useMemo(() => Object.fromEntries(
    processAnalytics.node_metrics.map((metric) => [metric.node_id, metric])
  ), [processAnalytics.node_metrics]);
  const edgeMetrics = useMemo(() => Object.fromEntries(
    processAnalytics.edge_metrics.map((metric) => [`${metric.source}:${metric.target}`, metric])
  ), [processAnalytics.edge_metrics]);
  const layers = useMemo(() => ['All', ...new Set(nodes.map((node) => node.data?.layer || 'Default'))], [nodes]);
  const displayNodes = useMemo(() => nodes.map((node) => ({
    ...node,
    hidden: activeLayer !== 'All' && (node.data?.layer || 'Default') !== activeLayer,
    data: {
      ...node.data,
      canResize: canManage,
      attachmentCount: attachmentCounts[node.id] || 0,
      intelligence: nodeMetrics[node.id] || null,
      planning: projectPlanning?.nodes?.[node.id] || null,
    },
  })), [activeLayer, attachmentCounts, canManage, nodeMetrics, nodes, projectPlanning]);
  const displayEdges = useMemo(() => edges.map((edge) => {
    const metric = edgeMetrics[`${edge.source}:${edge.target}`];
    if (!metric) return edge;
    return {
      ...edge,
      label: edge.label || `${metric.count}×`,
      style: {
        ...edge.style,
        stroke: metric.unexpected ? '#D6455D' : '#5B4BE7',
        strokeWidth: Math.min(5, 1.5 + Math.log2(metric.count + 1) * 0.7),
      },
    };
  }), [edgeMetrics, edges]);
  const currentDocument = useCallback(() => ({
    title,
    document_revision: documentRevision,
    description: projectDescription,
    status: projectStatus,
    profile: projectProfile,
    owner_id: projectOwnerId,
    collaborator_ids: projectCollaboratorIds,
    source_text: sourceText,
    graph: {
      title,
      nodes: nodes.map((node) => ({
        id: node.id, label: node.data.label, type: node.data.type || 'process',
        owner: node.data.owner || null, description: node.data.description || null, color: node.data.color || null,
        shape: node.data.shape || 'rounded', symbol: node.data.symbol || null,
        backup_owner: node.data.backup_owner || null, system: node.data.system || null,
        vendor: node.data.vendor || null, control_id: node.data.control_id || null,
        policy_reference: node.data.policy_reference || null,
        evidence_requirement: node.data.evidence_requirement || null,
        segregation_rule: node.data.segregation_rule || null,
        risk_level: node.data.risk_level || 'none',
        data_classification: node.data.data_classification || 'internal',
        sla_minutes: node.data.sla_minutes ? Number(node.data.sla_minutes) : null,
        review_date: node.data.review_date || null, required: Boolean(node.data.required),
        layer: node.data.layer || 'Default', parent_id: node.data.parent_id || null,
        width: Number(node.style?.width || node.width || 180),
        height: Number(node.style?.height || node.height || 76),
        x: node.position.x, y: node.position.y,
      })),
      edges: edges.map((edge) => ({
        source: edge.source, target: edge.target, label: edge.label || '', is_loop: Boolean(edge.animated),
        bidirectional: Boolean(edge.bidirectional),
      })),
      questions,
      warnings,
    },
  }), [documentRevision, edges, nodes, projectCollaboratorIds, projectDescription, projectOwnerId, projectProfile, projectStatus, questions, sourceText, title, warnings]);

  const applyCollaborativeDocument = useCallback((document) => {
    if (!document?.graph) return;
    resetHistory();
    lastDocumentSignatureRef.current = JSON.stringify(collaborativeDocument(document));
    const flow = toReactFlow(document.graph);
    setNodes(flow.nodes); setEdges(flow.edges); setTitle(document.title);
    setWarnings(document.graph.warnings || []); setQuestions(document.graph.questions || []);
    setSourceText(document.source_text || '');
  }, [resetHistory]);

  useEffect(() => {
    if (route.name !== 'editor' || !projectId) {
      collaborationRef.current?.disconnect();
      collaborationRef.current = null;
      setCollaborationStatus('offline'); setCollaborationReady(false); setCollaborators([]);
      setRemoteCursors({}); setProjectTasks([]); setProjectDeliverables([]); setProjectNotes([]); setCollaborationOpen(false);
      setProjectDetailsOpen(false);
      return undefined;
    }

    setCollaborationReady(false); setCollaborationError(''); setRemoteCursors({}); setProjectTasks([]); setProjectDeliverables([]); setProjectNotes([]);
    const client = new CollaborationClient(projectId, {
      onStatus: setCollaborationStatus,
      onError: setCollaborationError,
      onEvent: (event) => {
        if (event.type === 'presence') setCollaborators(event.users || []);
        if (event.type === 'snapshot') {
          applyCollaborativeDocument(event.document);
          setDocumentRevision(event.revision || 0);
          setProjectTasks(event.tasks || []);
          setProjectDeliverables(event.deliverables || []);
          setProjectNotes(event.notes || []);
          setCollaborationReady(true);
        }
        if (event.type === 'document' && event.actor_id !== user.id) {
          applyCollaborativeDocument(event.document);
          setDocumentRevision(event.revision || 0);
          setSaveConflict(null);
        }
        if (event.type === 'ack') {
          setDocumentRevision(event.revision || 0);
          setSaveConflict(null);
        }
        if (event.type === 'cursor') {
          setRemoteCursors((current) => ({ ...current, [event.user_id]: { ...event, seenAt: Date.now() } }));
        }
        if (event.type === 'cursor_removed') {
          setRemoteCursors((current) => {
            const next = { ...current }; delete next[event.user_id]; return next;
          });
        }
        if (event.type === 'task') {
          setProjectTasks((current) => current.some((task) => task.id === event.task.id)
            ? current : [...current, event.task]);
        }
        if (event.type === 'task_updated') {
          setProjectTasks((current) => current.map((task) => task.id === event.task.id ? event.task : task));
        }
        if (event.type === 'deliverable') {
          setProjectDeliverables((current) => current.some((item) => item.id === event.deliverable.id)
            ? current : [...current, event.deliverable]);
        }
        if (event.type === 'deliverable_updated') {
          setProjectDeliverables((current) => current.map((item) => item.id === event.deliverable.id
            ? event.deliverable : item));
        }
        if (event.type === 'note') {
          setProjectNotes((current) => current.some((note) => note.id === event.note.id)
            ? current : [...current, event.note]);
        }
        if (event.type === 'note_resolved') {
          setProjectNotes((current) => current.map((note) => note.id === event.id
            ? { ...note, resolved: event.resolved, resolved_at: event.resolved_at } : note));
        }
        if (event.type === 'error') {
          setCollaborationError(event.message || 'Live collaboration encountered an error.');
          if (event.code === 'CONFLICT') {
            setSaveConflict({ currentRevision: event.current_revision });
          }
        }
      },
    });
    collaborationRef.current = client;
    client.connect();
    return () => {
      client.disconnect();
      if (collaborationRef.current === client) collaborationRef.current = null;
    };
  }, [applyCollaborativeDocument, projectId, route.name, user.id]);

  useEffect(() => {
    if (!canManage || !collaborationReady || collaborationStatus !== 'connected' || !projectId) return undefined;
    const document = collaborativeDocument(currentDocument());
    const signature = JSON.stringify(document);
    if (signature === lastDocumentSignatureRef.current) return undefined;
    const timer = window.setTimeout(() => {
      if (saveInProgressRef.current) return;
      if (collaborationRef.current?.sendDocument(document, documentRevision)) {
        lastDocumentSignatureRef.current = signature;
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [canManage, collaborationReady, collaborationStatus, currentDocument, documentRevision, projectId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const cutoff = Date.now() - 10_000;
      setRemoteCursors((current) => Object.fromEntries(
        Object.entries(current).filter(([, cursor]) => cursor.seenAt >= cutoff)
      ));
    }, 3_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!canManage || route.name !== 'editor') return undefined;
    const handleUndoShortcut = (event) => {
      const target = event.target;
      const isEditingText = target instanceof HTMLElement && (
        target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
      );
      if (!isEditingText && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z' && !event.shiftKey) {
        event.preventDefault();
        undo();
      }
    };
    window.addEventListener('keydown', handleUndoShortcut);
    return () => window.removeEventListener('keydown', handleUndoShortcut);
  }, [canManage, route.name, undo]);

  const onNodesChange = useCallback((changes) => {
    const interactiveChanges = changes.filter((change) => change.type === 'position' || change.type === 'dimensions');
    if (interactiveChanges.length) {
      if (!nodeDragSnapshotRef.current) {
        nodeDragSnapshotRef.current = graphHistorySnapshot(graphStateRef.current);
      }
      if (interactiveChanges.some((change) => change.dragging === false || change.resizing === false)) {
        pushHistory(nodeDragSnapshotRef.current);
        nodeDragSnapshotRef.current = null;
      }
    }
    if (changes.some((change) => ['add', 'remove', 'reset'].includes(change.type))) {
      recordHistory('react-flow-structure', 120);
    }
    setNodes((current) => applyNodeChanges(changes, current));
  }, [pushHistory, recordHistory]);
  const onEdgesChange = useCallback((changes) => {
    if (changes.some((change) => ['add', 'remove', 'reset'].includes(change.type))) {
      recordHistory('react-flow-structure', 120);
    }
    setEdges((current) => applyEdgeChanges(changes, current));
  }, [recordHistory]);
  const onConnect = useCallback((connection) => {
    recordHistory();
    setEdges((current) => addEdge({
      ...connection,
      markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
      bidirectional: false,
    }, current));
  }, [recordHistory]);

  const generate = async () => {
    if (!prompt.trim() || isGenerating) return;
    setIsGenerating(true);
    setError('');
    try {
      const graph = await generateFlowchart(prompt);
      const flow = toReactFlow(graph);
      recordHistory();
      setNodes(flow.nodes); setEdges(flow.edges); setTitle(graph.title);
      setWarnings(graph.warnings || []); setQuestions(graph.questions || []); setPrompt('');
      setSourceText(prompt.trim());
      setHealth((current) => ({ ...current, api: 'online', model: true }));
    } catch (requestError) {
      setError(requestError.message);
      if (requestError.code === 'backend_unavailable') setHealth({ api: 'offline', model: false });
    } finally {
      setIsGenerating(false);
    }
  };

  const addDiagramObject = (template) => {
    recordHistory();
    const id = `node-${Date.now()}`;
    setNodes((current) => [...current, {
      id, type: 'flowNode', position: {
        x: 70 + (current.length % 2) * 260,
        y: 80 + Math.floor(current.length / 2) * 170,
      },
      style: { width: template.width || 180, height: template.height || 76 },
      zIndex: template.type === 'swimlane' ? -1 : 0,
      data: {
        label: template.label, type: template.type || 'process', shape: template.shape || 'rounded',
        symbol: template.symbol || null, color: template.color || null, layer: activeLayer === 'All' ? 'Default' : activeLayer,
        risk_level: 'none', data_classification: 'internal', required: false,
      },
    }]);
    setSelectedNodeId(id); setSelectedNodeIds([id]); setSelectedEdgeId(null); setDiagramLibraryOpen(false);
    window.requestAnimationFrame(() => window.requestAnimationFrame(
      () => reactFlowRef.current?.fitView({ padding: 0.24, maxZoom: 1.2, duration: 220 })
    ));
  };

  const autoLayout = () => {
    if (!nodes.length) return;
    recordHistory();
    const incoming = new Map(nodes.map((node) => [node.id, 0]));
    const outgoing = new Map(nodes.map((node) => [node.id, []]));
    edges.forEach((edge) => {
      if (!incoming.has(edge.source) || !incoming.has(edge.target)) return;
      incoming.set(edge.target, incoming.get(edge.target) + 1);
      outgoing.get(edge.source).push(edge.target);
    });
    const levels = new Map(); const queue = [...incoming].filter(([, count]) => count === 0).map(([id]) => id);
    queue.forEach((id) => levels.set(id, 0));
    while (queue.length) {
      const id = queue.shift();
      outgoing.get(id).forEach((target) => {
        levels.set(target, Math.max(levels.get(target) || 0, (levels.get(id) || 0) + 1));
        incoming.set(target, incoming.get(target) - 1); if (incoming.get(target) === 0) queue.push(target);
      });
    }
    nodes.forEach((node, index) => { if (!levels.has(node.id)) levels.set(node.id, Math.max(0, ...levels.values()) + 1 + Math.floor(index / 6)); });
    const rows = {};
    setNodes((current) => current.map((node) => { const level = levels.get(node.id); const row = rows[level] || 0; rows[level] = row + 1; return { ...node, position: { x: 100 + level * 280, y: 90 + row * 150 } }; }));
    window.setTimeout(() => reactFlowRef.current?.fitView({ padding: .2, duration: 300 }), 0);
  };

  const updateSelectedNode = (updates) => {
    recordHistory(`node:${selectedNodeId}:${Object.keys(updates).sort().join('-')}`);
    setNodes((current) => current.map((node) => {
    if (node.id !== selectedNodeId) return node;
    const data = { ...node.data, ...updates };
    return { ...node, data };
    }));
  };
  const updateSelectedEdge = (label) => {
    recordHistory(`edge:${selectedEdgeId}:label`);
    setEdges((current) => current.map(
      (edge) => edge.id === selectedEdgeId ? { ...edge, label } : edge
    ));
  };

  const updateSelectedNodeSize = (dimension, rawValue) => {
    const minimum = dimension === 'width' ? 80 : 44;
    const maximum = dimension === 'width' ? 720 : 520;
    const value = Math.max(minimum, Math.min(maximum, Number(rawValue) || minimum));
    recordHistory(`node:${selectedNodeId}:${dimension}`);
    setNodes((current) => current.map((node) => node.id === selectedNodeId
      ? { ...node, style: { ...node.style, [dimension]: value } }
      : node));
  };

  const toggleBidirectional = (enabled) => {
    recordHistory();
    setEdges((current) => current.map((edge) => {
      if (edge.id !== selectedEdgeId) return edge;
      return {
        ...edge,
        bidirectional: enabled,
        markerStart: enabled ? { type: MarkerType.ArrowClosed, width: 18, height: 18 } : undefined,
      };
    }));
  };

  const removeSelection = () => {
    recordHistory();
    if (selectedNodeId || selectedNodeIds.length) {
      const ids = new Set(selectedNodeIds.length ? selectedNodeIds : [selectedNodeId]);
      setNodes((current) => current.filter((node) => !ids.has(node.id)));
      setEdges((current) => current.filter((edge) => !ids.has(edge.source) && !ids.has(edge.target)));
      setSelectedNodeId(null);
      setSelectedNodeIds([]);
    } else if (selectedEdgeId) {
      setEdges((current) => current.filter((edge) => edge.id !== selectedEdgeId));
      setSelectedEdgeId(null);
    }
  };

  const duplicateSelectedNode = () => {
    if (!selectedNode) return;
    recordHistory();
    const id = `node-${Date.now()}`;
    const copy = {
      ...selectedNode,
      id,
      position: { x: selectedNode.position.x + 36, y: selectedNode.position.y + 36 },
      data: { ...selectedNode.data, label: `${selectedNode.data.label} copy` },
      selected: false,
    };
    setNodes((current) => [...current, copy]);
    setSelectedNodeId(id);
    setSelectedNodeIds([id]);
  };

  const alignSelection = (mode) => {
    const chosen = nodes.filter((node) => selectedNodeIds.includes(node.id));
    if (chosen.length < 2) return;
    recordHistory();
    if (mode === 'left') {
      const left = Math.min(...chosen.map((node) => node.position.x));
      setNodes((current) => current.map((node) => selectedNodeIds.includes(node.id)
        ? { ...node, position: { ...node.position, x: left } }
        : node));
      return;
    }
    const sorted = [...chosen].sort((first, second) => first.position.y - second.position.y);
    const top = sorted[0].position.y;
    const bottom = sorted.at(-1).position.y;
    const gap = sorted.length > 1 ? (bottom - top) / (sorted.length - 1) : 0;
    const positions = Object.fromEntries(sorted.map((node, index) => [node.id, top + gap * index]));
    setNodes((current) => current.map((node) => positions[node.id] === undefined
      ? node
      : { ...node, position: { ...node.position, y: positions[node.id] } }));
  };

  const clearAll = () => {
    if (!isAdmin) return;
    recordHistory();
    setNodes([]); setEdges([]); setWarnings([]); setQuestions([]);
    setSelectedNodeId(null); setSelectedNodeIds([]); setSelectedEdgeId(null); setTitle('Untitled process');
    setClearCanvasOpen(false);
  };

  const exportImage = useCallback(async () => {
    const canvas = document.querySelector('.flow-canvas .react-flow');
    if (!canvas) throw new Error('The diagram canvas is unavailable.');
    try {
      const dataUrl = await toPng(canvas, {
        backgroundColor: resolvedTheme === 'dark' ? '#101522' : '#F7F9FC',
        pixelRatio: 2,
      });
      const link = document.createElement('a');
      link.download = `${title.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'workflow'}.png`;
      link.href = dataUrl;
      document.body.appendChild(link);
      link.click();
      link.remove();
      return link.download;
    } catch (exportError) {
      const message = 'The diagram could not be exported.';
      setError(message);
      throw new Error(message, { cause: exportError });
    }
  }, [title, resolvedTheme]);

  const handleCanvasPointerMove = useCallback((event) => {
    const now = performance.now();
    if (now - cursorSentAtRef.current < 40) return;
    cursorSentAtRef.current = now;
    const bounds = event.currentTarget.getBoundingClientRect();
    collaborationRef.current?.sendCursor(
      (event.clientX - bounds.left) / bounds.width,
      (event.clientY - bounds.top) / bounds.height
    );
  }, []);

  const handleSelectionChange = useCallback(({ nodes: selectedNodes }) => {
    const ids = selectedNodes.map((node) => node.id);
    setSelectedNodeIds((current) => (
      current.length === ids.length && current.every((id, index) => id === ids[index]) ? current : ids
    ));
    setSelectedNodeId((current) => {
      const next = ids.length === 1 ? ids[0] : null;
      return current === next ? current : next;
    });
  }, []);

  const createProjectTask = (task) => collaborationRef.current?.createTask(task);
  const updateProjectTask = (taskId, changes) => collaborationRef.current?.updateTask(taskId, changes);
  const createProjectDeliverable = (deliverable) => collaborationRef.current?.createDeliverable(deliverable);
  const updateProjectDeliverable = (deliverableId, changes) => collaborationRef.current?.updateDeliverable(deliverableId, changes);
  const sendProjectNote = (body, mentionedUserIds, nodeId) => collaborationRef.current?.sendNote(
    body, mentionedUserIds, nodeId
  );
  const resolveProjectNote = (noteId, resolved) => collaborationRef.current?.resolveNote(noteId, resolved);
  const attachFile = async (file, nodeId) => {
    if (!projectId) throw new Error('Save this workflow before attaching files.');
    const attachment = await uploadAttachment(projectId, nodeId, file);
    setAttachments((current) => [...current, attachment]);
  };
  const removeAttachment = async (attachmentId) => {
    if (!projectId) return;
    await deleteAttachment(projectId, attachmentId);
    setAttachments((current) => current.filter((attachment) => attachment.id !== attachmentId));
  };

  const modelStatus = health.api === 'online' && health.model;

  useEffect(() => {
    if (route.name === 'editor' && new URLSearchParams(window.location.search).get('ai') === '1') {
      setAiPanelOpen(true);
    }
  }, [route]);

  const loadMoreProjects = async () => {
    if (!projectNextCursor || projectsLoadingMore) return;
    setProjectsLoadingMore(true);
    try {
      const page = await searchProjects({
        search: projectSearch,
        after: projectNextCursor,
        first: 24,
      });
      setProjects((current) => [
        ...current,
        ...page.items.filter((item) => !current.some((existing) => existing.id === item.id)),
      ]);
      setProjectNextCursor(page.next_cursor);
      setProjectTotalCount(page.total_count);
    } catch {
      setProjectsState('error');
    } finally {
      setProjectsLoadingMore(false);
    }
  };

  const navigate = (path) => {
    window.history.pushState({}, '', path);
    document.documentElement.scrollLeft = 0;
    document.documentElement.scrollTop = 0;
    document.body.scrollLeft = 0;
    document.body.scrollTop = 0;
    const nextRoute = routeFromPath();
    if (nextRoute.projectId) setProjectId(nextRoute.projectId);
    if (!nextRoute.projectId) setProjectAccess(isAdmin ? 'admin' : null);
    setAiPanelOpen(false);
    setRoute(nextRoute);
  };

  const createNewProject = () => {
    if (!workspaceCanManage) return;
    resetHistory();
    setNodes([]); setEdges([]); setWarnings([]); setQuestions([]); setPrompt(''); setSourceText('');
    setSelectedNodeId(null); setSelectedEdgeId(null); setTitle('Untitled process'); setProjectId(null); setError('');
    setDocumentRevision(0); setSaveConflict(null);
    setProjectDescription(''); setProjectStatus('active'); setProjectApprovalStatus('draft');
    setProjectProfile(EMPTY_PROJECT_PROFILE);
    setProjectAccess(isAdmin ? 'admin' : 'editor'); setProjectOwnerId(user.id);
    setProjectCollaboratorIds([user.id]); setProjectDetailsOpen(false);
    setDiagramLibraryOpen(false); setAttachments([]);
    localStorage.removeItem(`${storagePrefix}:projectId`);
    navigate('/editor');
  };

  const hydrateProjectDetails = (project) => {
    setProjectDescription(project.description || '');
    setProjectStatus(project.status || 'active');
    setProjectProfile({ ...EMPTY_PROJECT_PROFILE, ...(project.profile || {}) });
    setProjectApprovalStatus(project.approval_status || 'draft');
    setProjectAccess(project.current_user_access || (isAdmin ? 'admin' : 'viewer'));
    setProjectOwnerId(project.owner?.id || user.id);
    setProjectCollaboratorIds(project.collaborators?.map((member) => member.id) || [project.owner?.id || user.id]);
    setDocumentRevision(project.document_revision || 0);
    setSaveConflict(null);
  };

  const hydrateRestoredProject = (project) => {
    const flow = toReactFlow(project.graph);
    setNodes(flow.nodes); setEdges(flow.edges); setTitle(project.title);
    setWarnings(project.graph.warnings || []); setQuestions(project.graph.questions || []);
    setSourceText(project.source_text || '');
    collaborationRef.current?.setDocumentRevision(project.document_revision || 0);
    lastDocumentSignatureRef.current = JSON.stringify(collaborativeDocument(project));
    hydrateProjectDetails(project);
    resetHistory();
  };

  const reloadLatestProject = async () => {
    if (!projectId) return;
    setSaveState('saving'); setError('');
    try {
      const project = await getProject(projectId);
      hydrateRestoredProject(project);
      setSaveConflict(null);
      setCollaborationError('');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaveState('idle');
    }
  };

  const save = async () => {
    if (!canManage || !nodes.length || saveInProgressRef.current) return;
    saveInProgressRef.current = true;
    setSaveState('saving');
    setError('');
    try {
      const client = collaborationRef.current;
      if (client && collaborationStatus === 'connected') await client.flushDocumentWrites();
      const document = currentDocument();
      document.document_revision = client?.getDocumentRevision(document.document_revision)
        ?? document.document_revision;
      const saved = await saveProject(projectId, document);
      client?.setDocumentRevision(saved.document_revision);
      lastDocumentSignatureRef.current = JSON.stringify(collaborativeDocument(saved));
      setProjectId(saved.id);
      hydrateProjectDetails(saved);
      getProjectPlanning(saved.id).then(setProjectPlanning).catch(() => {});
      localStorage.setItem(`${storagePrefix}:projectId`, saved.id);
      if (window.location.pathname !== `/projects/${saved.id}`) {
        window.history.replaceState({}, '', `/projects/${saved.id}`);
        setRoute({ name: 'editor', projectId: saved.id });
      }
      setSaveState('saved');
      window.setTimeout(() => setSaveState('idle'), 1800);
    } catch (requestError) {
      if (requestError.code === 'CONFLICT') {
        setError('');
        setSaveConflict({ currentRevision: requestError.details?.currentRevision });
      } else {
        setError(requestError.message);
      }
      setSaveState('idle');
    } finally {
      saveInProgressRef.current = false;
    }
  };

  const saveProjectDetails = async (details) => {
    if (!projectId) {
      setProjectDescription(details.description); setProjectStatus(details.status);
      setProjectProfile({ ...EMPTY_PROJECT_PROFILE, ...(details.profile || {}) });
      setProjectOwnerId(details.owner_id); setProjectCollaboratorIds(details.collaborator_ids);
      return;
    }
    if (saveInProgressRef.current) return;
    saveInProgressRef.current = true;
    setSaveState('saving'); setError('');
    try {
      const client = collaborationRef.current;
      if (client && collaborationStatus === 'connected') await client.flushDocumentWrites();
      const document = { ...currentDocument(), ...details };
      document.document_revision = client?.getDocumentRevision(document.document_revision)
        ?? document.document_revision;
      const saved = await saveProject(projectId, document);
      client?.setDocumentRevision(saved.document_revision);
      lastDocumentSignatureRef.current = JSON.stringify(collaborativeDocument(saved));
      hydrateProjectDetails(saved);
      setSaveState('saved');
      window.setTimeout(() => setSaveState('idle'), 1800);
    } catch (requestError) {
      if (requestError.code === 'CONFLICT') {
        setError('');
        setSaveConflict({ currentRevision: requestError.details?.currentRevision });
      } else {
        setError(requestError.message);
      }
      setSaveState('idle');
      throw requestError;
    } finally {
      saveInProgressRef.current = false;
    }
  };

  if (route.name === 'work') {
    return <WorkManagement user={user} onNavigate={navigate} navigationKey={window.location.search} />;
  }

  if (route.name === 'calendar') {
    return <CalendarManagement user={user} onNavigate={navigate} navigationKey={window.location.search} />;
  }

  if (route.name === 'knowledge') {
    return <KnowledgeManagement user={user} onNavigate={navigate} navigationKey={window.location.search} />;
  }

  if (route.name === 'service') {
    return <ServiceDesk user={user} onNavigate={navigate} navigationKey={window.location.search} />;
  }

  if (route.name === 'operations') {
    return <EnterpriseManagement user={user} onNavigate={navigate} navigationKey={window.location.search} />;
  }
  if (route.name === 'admin') {
    if (user.role !== 'admin') return <main id="workspace-main" className="dashboard-shell"><WorkspaceTopNav active="home" onNavigate={navigate} role={user.role} /><section className="dashboard-empty"><h1>Administrator access required</h1><p>This control plane is limited to workspace administrators.</p></section></main>;
    return <PlatformAdmin user={user} onNavigate={navigate} navigationKey={window.location.search} />;
  }

  if (route.name === 'dashboard') {
    return <main id="workspace-main" className="dashboard-shell">
      <WorkspaceTopNav active="home" onNavigate={navigate} role={user.role} status={<span className={`status-pill ${modelStatus ? 'online' : ''}`}><span className="status-dot" />
        {health.api === 'checking' ? 'Connecting…' : modelStatus ? 'Assistant ready' : 'Assistant unavailable'}
      </span>} />
      <HomeDashboard user={user} recentProjects={projects} projectTotalCount={projectTotalCount}
        projectsState={projectsState} onNavigate={navigate} />
    </main>;
  }

  if (route.name === 'workflows') {
    return (
      <main id="workspace-main" className="dashboard-shell">
        <WorkspaceTopNav active="workflows" onNavigate={navigate} role={user.role} status={<span className={`status-pill ${modelStatus ? 'online' : ''}`}><span className="status-dot" />
          {health.api === 'checking' ? 'Connecting…' : modelStatus ? 'Assistant ready' : 'Assistant unavailable'}
        </span>} />
        <section className="dashboard-content">
          <div className="dashboard-hero">
            <div><p className="eyebrow">{user.entity_name || 'Workspace'}</p><h1>Workflows</h1>
              <p>{workspaceCanManage ? 'Create, govern, and connect process maps to the work that delivers them.' : 'Explore the process maps shared with you and follow their delivery progress.'}</p></div>
            {workspaceCanManage && <div className="workflow-hero-actions"><button className="button secondary" onClick={() => navigate('/operations?tab=approvals')}>Governed changes</button><button className="button primary dashboard-new" onClick={createNewProject}>Create workflow</button></div>}
          </div>
          <div className="project-discovery">
            <label><span>⌕</span><input type="search" aria-label="Search workflows"
              value={projectSearch} onChange={(event) => setProjectSearch(event.target.value)}
              placeholder="Search workflows by title or description" /></label>
            {projectsState === 'ready' && <span>{projectTotalCount.toLocaleString()} {projectTotalCount === 1 ? 'workflow' : 'workflows'}</span>}
          </div>

          {projectsState === 'loading' && <div className="dashboard-message"><span className="spinner dark" /> Loading projects…</div>}
          {projectsState === 'error' && <div className="notice error dashboard-message"><strong>Couldn’t load projects</strong><span>Please refresh the page or try again in a moment.</span></div>}
          {projectsState === 'ready' && projects.length === 0 && <div className="dashboard-empty">
            <div className="empty-icon">↳</div><h2>{projectSearch ? 'No matching workflows' : workspaceCanManage ? 'No saved workflows yet' : 'No workflows have been shared yet'}</h2>
            <p>{projectSearch ? 'Try a different title or description.' : workspaceCanManage ? 'Create your first process map and save it to see it here.' : 'An entity admin can create the first process map and share it with you.'}</p>
            {workspaceCanManage && !projectSearch && <button className="button primary" onClick={createNewProject}>Create your first workflow</button>}
          </div>}
          {projects.length > 0 && <div className="project-grid">
            {projects.map((project, index) => <button className="project-card" key={project.id} onClick={() => navigate(`/projects/${project.id}`)}>
              <div className={`project-preview preview-${index % 4}`}>
                <span className={`project-status-badge ${project.status || 'active'}`}>{project.status || 'active'}</span>
                <span className="preview-node one" /><span className="preview-line" /><span className="preview-node two" />
                <span className="preview-line branch" /><span className="preview-node three" />
              </div>
              <div className="project-card-body"><h2>{project.title}</h2>
                {(project.profile?.key || project.profile?.priority || project.profile?.health) && <div className="project-profile-badges">
                  {project.profile?.key && <span className="key">{project.profile.key}</span>}
                  {project.profile?.priority && <span className={`priority ${project.profile.priority}`}>{project.profile.priority}</span>}
                  {project.profile?.health && project.profile.health !== 'unknown' && <span className={`health ${project.profile.health}`}>{project.profile.health.replaceAll('_', ' ')}</span>}
                </div>}
                <p className={`project-card-description ${project.description ? '' : 'empty'}`}>{project.description || 'No description added yet.'}</p>
                <div className="project-meta"><span>{countLabel(project.node_count, 'step')}</span><span>{countLabel(project.edge_count, 'connection')}</span></div>
                {((project.deliverable_count || 0) > 0 || (project.task_count || 0) > 0) && <div className="project-plan-summary">
                  <span><strong>Delivery progress</strong><b>{project.plan_progress || 0}%</b></span>
                  <i><b style={{ width: `${project.plan_progress || 0}%` }} /></i>
                  <small>{project.completed_deliverable_count || 0}/{project.deliverable_count || 0} deliverables · {project.completed_task_count || 0}/{project.task_count || 0} tasks</small>
                </div>}
                <div className="project-card-footer"><span className="project-card-owner">
                  <span className="project-card-avatar" style={{ '--avatar-color': project.owner?.color || '#667085' }}>{initials(project.owner?.display_name || 'Unassigned')}</span>
                  <span><small>Owner</small><strong>{project.owner?.display_name || 'Unassigned'}</strong></span>
                </span><span className="project-card-collaborators">{(project.collaborators || []).slice(0, 3).map((member) =>
                  <span className="project-card-avatar" style={{ '--avatar-color': member.color }} title={member.display_name} key={member.id}>{initials(member.display_name)}</span>)}
                  {(project.collaborator_count || 0) > 3 && <b>+{project.collaborator_count - 3}</b>}</span></div>
                <span className="project-updated">Updated {formatUpdatedAt(project.updated_at)}</span>
              </div>
            </button>)}
          </div>}
          {projectNextCursor && <div className="project-load-more"><button className="button secondary"
            disabled={projectsLoadingMore} onClick={loadMoreProjects}>{projectsLoadingMore ? 'Loading…' : `Load more (${projects.length} of ${projectTotalCount})`}</button></div>}
        </section>
      </main>
    );
  }

  return (
    <main id="workspace-main" className={`app-shell ${presentationMode ? 'presentation-mode' : ''}`}>
      <WorkspaceTopNav active="workflows" onNavigate={navigate} role={user.role} showIdentity={false} context={<input className="title-input"
        aria-label="Workflow title" value={title} readOnly={!canManage}
        onChange={(event) => { recordHistory('flowchart-title'); setTitle(event.target.value); }} />} />

      <section className="workspace">
        {workspaceCanManage && aiPanelOpen && <aside className="left-panel ai-panel" aria-label="AI workflow assistant">
          <div className="ai-panel-heading"><div><p className="eyebrow">AI assistant</p><h1>Turn process text into a working map.</h1></div>
            <button className="icon-button" aria-label="Close AI assistant" onClick={() => setAiPanelOpen(false)}>×</button></div>
          <p className="supporting-copy">Describe a process and Workspace will turn it into a structured, editable workflow.</p>
          <label className="prompt-label" htmlFor="flow-prompt">Describe the process</label>
          <textarea id="flow-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') generate(); }}
            placeholder="Example: A customer submits a request. Support triages it. If billing-related, route it to Finance; otherwise assign it to Engineering..." />
          <div className="prompt-meta"><span>{prompt.length.toLocaleString()} characters</span><span>⌘ Enter to generate</span></div>
          <button className="button primary generate-button" disabled={!prompt.trim() || isGenerating} onClick={generate}>
            {isGenerating ? <><span className="spinner" /> Analyzing process…</> : 'Generate workflow'}
          </button>
          {error && <div className="notice error" role="alert"><strong>Something went wrong</strong><span>{error}</span></div>}
          {(warnings.length > 0 || questions.length > 0) && <div className="insights"><p className="eyebrow">Workspace review</p>
            {warnings.map((warning) => <div className="insight" key={`${warning.code}-${warning.message}`}>⚠ {warning.message}</div>)}
            {questions.map((question) => <div className="insight question" key={question}>? {question}</div>)}
          </div>}
        </aside>}

        <section className="canvas-panel">
          <div className="canvas-toolbar" role="toolbar" aria-label="Workflow tools">{workspaceCanManage && <button className={`tool-button ai-assistant-button ${aiPanelOpen ? 'active' : ''}`}
            aria-label="AI assistant" aria-expanded={aiPanelOpen} onClick={() => setAiPanelOpen((open) => !open)}>
              <AiSparkIcon /><span>AI</span>
            </button>}
            {canManage && <>
            <button className={`tool-button ${diagramLibraryOpen ? 'active' : ''}`}
            aria-expanded={diagramLibraryOpen} onClick={() => setDiagramLibraryOpen((open) => !open)}>＋ Add</button>
            <button className="tool-button undo-button" aria-label="Undo last canvas change" title="Undo last canvas change (⌘Z)"
              disabled={historyDepth === 0} onClick={undo}>↶ Undo</button></>}
            <button className="tool-button" disabled={!nodes.length} onClick={autoLayout}>Auto layout</button>
            <button className={`tool-button ${presentationMode ? 'active' : ''}`} disabled={!nodes.length} onClick={() => setPresentationMode((value) => !value)}>{presentationMode ? 'Exit present' : 'Present'}</button>
            <button className={`tool-button ${focusSeconds ? 'active' : ''}`} onClick={() => setFocusSeconds((value) => value ? 0 : 300)}>{focusSeconds ? `${String(Math.floor(focusSeconds / 60)).padStart(2, '0')}:${String(focusSeconds % 60).padStart(2, '0')}` : '5m timer'}</button>
            <div className="workflow-view-switch" role="tablist" aria-label="Workflow views">
              {['diagram', 'sheet', 'split'].map((view) => <button role="tab" key={view}
                aria-selected={workflowView === view} className={workflowView === view ? 'active' : ''}
                onClick={() => setWorkflowView(view)}>{view === 'diagram' ? 'Diagram' : view === 'sheet' ? 'Sheet' : 'Split'}</button>)}
            </div>
            <button className={`tool-button observe-button ${intelligenceOpen ? 'active' : ''}`}
              disabled={!projectId} onClick={() => setIntelligenceOpen((current) => !current)}>
              ◉ Observe{processAnalytics.insights.filter((insight) => insight.status === 'open').length > 0
                && <span>{processAnalytics.insights.filter((insight) => insight.status === 'open').length}</span>}
            </button>
            <label className="layer-control">Layer<select value={activeLayer} onChange={(event) => setActiveLayer(event.target.value)}>
              {layers.map((layer) => <option key={layer} value={layer}>{layer}</option>)}
            </select></label>
            {canManage && selectedNodeIds.length > 1 && <>
              <button className="tool-button" onClick={() => alignSelection('left')}>Align left</button>
              <button className="tool-button" onClick={() => alignSelection('vertical')}>Distribute</button>
            </>}
            {isAdmin && <button className="tool-button danger" disabled={!nodes.length && !edges.length}
              onClick={() => setClearCanvasOpen(true)}>Clear canvas</button>}
            {!canManage && <span className="read-only-badge">View only</span>}
            <span className="toolbar-divider" aria-hidden="true" />
            <button className="project-context" aria-label="Project details" onClick={() => setProjectDetailsOpen(true)}>
              <span className="project-context-name">Project details</span>
              <span className={`project-status-label ${projectStatus}`}>{projectStatus}</span>
              <span className={`project-approval-label ${projectApprovalStatus}`}>{projectApprovalStatus.replace('_', ' ')}</span>
              <span>Owner <strong>{projectOwner.display_name}</strong></span>
              <span>{countLabel(projectCollaboratorIds.length, 'collaborator')}</span>
            </button>
            <span className={`status-pill toolbar-model-status ${modelStatus ? 'online' : ''}`}><span className="status-dot" />
              {health.api === 'checking' ? 'Connecting…' : modelStatus ? 'Assistant ready' : 'Assistant unavailable'}
            </span>
            {projectId && <PresenceStack users={collaborators} status={collaborationStatus} />}
            {projectId && <button className={`tool-button chat-button ${collaborationOpen ? 'active' : ''}`}
              onClick={() => setCollaborationOpen((current) => !current)}>Collaborate{(projectTasks.filter((task) => task.status !== 'done').length + projectNotes.filter((note) => !note.resolved).length) > 0
                && <span>{projectTasks.filter((task) => task.status !== 'done').length + projectNotes.filter((note) => !note.resolved).length}</span>}</button>}
            {canManage && <button className="tool-button" disabled={!nodes.length || saveState === 'saving'} onClick={save}>
              {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved' : 'Save project'}
            </button>}
            <ProjectExportMenu projectId={projectId} canManage={canManage} onExportPng={exportImage} />
            {collaborationError && <span className="collaboration-error" title={collaborationError}>Live sync issue</span>}
            <span className="canvas-count">{countLabel(nodes.length, 'step')} · {countLabel(edges.length, 'connection')}</span></div>
          <DiagramLibrary open={diagramLibraryOpen} onClose={() => setDiagramLibraryOpen(false)} onAdd={addDiagramObject} />
          {error && !aiPanelOpen && <div className="canvas-error notice error" role="alert">
            <strong>Something went wrong</strong><span>{error}</span>
          </div>}
          {saveConflict && <div className="save-conflict" role="alert">
            <span><strong>Newer workflow changes are available</strong>
              <small>Your canvas was not overwritten. Reload before making another save.</small></span>
            <button className="button secondary" disabled={saveState === 'saving'} onClick={reloadLatestProject}>
              Reload latest
            </button>
          </div>}
          <div className={`workflow-view-body ${workflowView}`}>
          {workflowView !== 'sheet' && <div className="flow-canvas" onMouseMove={handleCanvasPointerMove}>
            {nodes.length === 0 && <div className="empty-state"><div className="empty-icon">↳</div><h2>Your process will appear here</h2><p>Describe a workflow, or choose Add to place an object manually.</p></div>}
            <ReactFlow nodes={displayNodes} edges={displayEdges} nodeTypes={NODE_TYPES} connectionMode={ConnectionMode.Loose}
              onInit={(instance) => { reactFlowRef.current = instance; }}
              snapToGrid snapGrid={[16, 16]} selectionOnDrag multiSelectionKeyCode={['Meta', 'Control']}
              nodesDraggable={canManage} nodesConnectable={canManage} deleteKeyCode={canManage ? ['Backspace', 'Delete'] : null}
              onNodesChange={canManage ? onNodesChange : undefined} onEdgesChange={canManage ? onEdgesChange : undefined}
              onConnect={canManage ? onConnect : undefined} onNodeClick={(_, node) => { setSelectedNodeId(node.id); setSelectedEdgeId(null); }}
              onEdgeClick={(_, edge) => { setSelectedEdgeId(edge.id); setSelectedNodeId(null); }}
              onSelectionChange={handleSelectionChange}
              onPaneClick={() => { setSelectedNodeId(null); setSelectedNodeIds([]); setSelectedEdgeId(null); }} fitView fitViewOptions={{ padding: 0.14, minZoom: 0.55, maxZoom: 1.2 }} minZoom={0.25}>
              <MiniMap pannable zoomable nodeColor={(node) => node.data?.color || NODE_COLORS[node.data?.type] || '#DCE3EC'} />
              <Background color={resolvedTheme === 'dark' ? '#394256' : '#D7DEE8'} gap={22} size={1} /><Controls />
            </ReactFlow>
            <RemoteCursors cursors={remoteCursors} />
          </div>}
          {workflowView !== 'diagram' && <WorkflowSheet nodes={nodes} tasks={projectTasks}
            deliverables={projectDeliverables} contacts={communicationContacts} currentUser={user}
            connected={collaborationStatus === 'connected'} canManage={canManage}
            onCreateTask={createProjectTask} onUpdateTask={updateProjectTask}
            onCreateDeliverable={createProjectDeliverable} onUpdateDeliverable={updateProjectDeliverable}
            onSelectNode={(nodeId) => {
              setSelectedNodeId(nodeId); setSelectedNodeIds([nodeId]); setSelectedEdgeId(null);
              if (workflowView === 'sheet') setWorkflowView('diagram');
              window.setTimeout(() => reactFlowRef.current?.fitView({ nodes: [{ id: nodeId }], padding: 1.4, duration: 220 }), 0);
            }} />}
          </div>
        </section>

        {workflowView !== 'sheet' && (selectedNode || selectedEdge) && <aside className="properties-panel">
          <div className="properties-heading"><div><p className="eyebrow">Inspector</p><h2>{selectedNode ? 'Step properties' : 'Connection'}</h2></div>
            <button className="icon-button" aria-label="Close inspector" onClick={() => { setSelectedNodeId(null); setSelectedEdgeId(null); }}>×</button></div>
          {selectedNode ? <>
            <label>Label<input value={selectedNode.data.label || ''} disabled={!canManage} onChange={(event) => updateSelectedNode({ label: event.target.value })} /></label>
            <div className="node-size-fields"><label>Width<NodeSizeInput dimension="width" disabled={!canManage}
              value={Number(selectedNode.style?.width || selectedNode.width || 180)}
              onCommit={updateSelectedNodeSize} /></label>
              <label>Height<NodeSizeInput dimension="height" disabled={!canManage}
                value={Number(selectedNode.style?.height || selectedNode.height || 76)}
                onCommit={updateSelectedNodeSize} /></label></div>
            <label>Type<select value={selectedNode.data.type || 'process'} disabled={!canManage} onChange={(event) => updateSelectedNode({ type: event.target.value })}>
              {Object.keys(NODE_COLORS).map((type) => <option key={type} value={type}>{type.replace('_', ' ')}</option>)}</select></label>
            <fieldset className="color-fieldset">
              <legend>Node color</legend>
              <div className="node-color-palette">
                {COLOR_PALETTE.map((color) => <button key={color.value} type="button" aria-label={`Set node color to ${color.name}`}
                  title={color.name} disabled={!canManage} className={selectedNode.data.color === color.value ? 'selected' : ''}
                  style={{ backgroundColor: color.value }} onClick={() => updateSelectedNode({ color: color.value })} />)}
                <button type="button" disabled={!canManage} className={`type-default ${!selectedNode.data.color ? 'selected' : ''}`}
                  onClick={() => updateSelectedNode({ color: null })}>Type default</button>
              </div>
            </fieldset>
            <label>Layer<input value={selectedNode.data.layer || 'Default'} disabled={!canManage} list="flowchart-layers"
              onChange={(event) => updateSelectedNode({ layer: event.target.value || 'Default' })} /></label>
            <datalist id="flowchart-layers">{layers.filter((layer) => layer !== 'All').map((layer) => <option key={layer} value={layer} />)}</datalist>
            <label>Description<textarea value={selectedNode.data.description || ''} disabled={!canManage} placeholder="What happens in this step?" onChange={(event) => updateSelectedNode({ description: event.target.value })} /></label>
            <NodePlanningPanel key={selectedNode.id} projectId={projectId} node={selectedNode}
              planning={projectPlanning} canManage={canManage} onPlanningChange={setProjectPlanning}
              onNavigate={navigate} />
            <details className="inspector-section" open>
              <summary>Ownership & systems</summary>
              <label>Owner<input value={selectedNode.data.owner || ''} disabled={!canManage} placeholder="Primary role or person" onChange={(event) => updateSelectedNode({ owner: event.target.value })} /></label>
              <label>Backup owner<input value={selectedNode.data.backup_owner || ''} disabled={!canManage} placeholder="Escalation backup" onChange={(event) => updateSelectedNode({ backup_owner: event.target.value })} /></label>
              <label>System<input value={selectedNode.data.system || ''} disabled={!canManage} placeholder="Application or platform" onChange={(event) => updateSelectedNode({ system: event.target.value })} /></label>
              <label>Vendor<input value={selectedNode.data.vendor || ''} disabled={!canManage} placeholder="External dependency" onChange={(event) => updateSelectedNode({ vendor: event.target.value })} /></label>
            </details>
            <details className="inspector-section">
              <summary>Controls & risk</summary>
              <label>Control ID<input value={selectedNode.data.control_id || ''} disabled={!canManage} placeholder="CTRL-001" onChange={(event) => updateSelectedNode({ control_id: event.target.value })} /></label>
              <label>Risk level<select value={selectedNode.data.risk_level || 'none'} disabled={!canManage} onChange={(event) => updateSelectedNode({ risk_level: event.target.value })}>
                {['none', 'low', 'medium', 'high', 'critical'].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label>Policy reference<input value={selectedNode.data.policy_reference || ''} disabled={!canManage} placeholder="Policy or procedure" onChange={(event) => updateSelectedNode({ policy_reference: event.target.value })} /></label>
              <label>Evidence requirement<textarea value={selectedNode.data.evidence_requirement || ''} disabled={!canManage} placeholder="What proves completion?" onChange={(event) => updateSelectedNode({ evidence_requirement: event.target.value })} /></label>
              <label>Segregation rule<textarea value={selectedNode.data.segregation_rule || ''} disabled={!canManage} placeholder="Who must not perform or approve both steps?" onChange={(event) => updateSelectedNode({ segregation_rule: event.target.value })} /></label>
              <label>Data classification<select value={selectedNode.data.data_classification || 'internal'} disabled={!canManage} onChange={(event) => updateSelectedNode({ data_classification: event.target.value })}>
                {['public', 'internal', 'confidential', 'restricted'].map((value) => <option key={value}>{value}</option>)}</select></label>
            </details>
            <details className="inspector-section">
              <summary>Service level & review</summary>
              <label>SLA (minutes)<input type="number" min="1" value={selectedNode.data.sla_minutes || ''} disabled={!canManage} placeholder="For example: 240"
                onChange={(event) => updateSelectedNode({ sla_minutes: event.target.value })} /></label>
              <label>Review date<input type="date" value={selectedNode.data.review_date || ''} disabled={!canManage} onChange={(event) => updateSelectedNode({ review_date: event.target.value })} /></label>
              <label className="checkbox-detail"><input type="checkbox" checked={Boolean(selectedNode.data.required)} disabled={!canManage}
                onChange={(event) => updateSelectedNode({ required: event.target.checked })} /><span><strong>Required step</strong><small>Skipped cases create drift alerts</small></span></label>
            </details>
            {nodeMetrics[selectedNode.id] && <section className="selected-node-metrics"><strong>Observed performance</strong>
              <span>{nodeMetrics[selectedNode.id].count} executions</span>
              <span>{Math.round(nodeMetrics[selectedNode.id].average_wait_seconds / 60)}m average wait</span>
              <span>{nodeMetrics[selectedNode.id].failure_count} failures · {nodeMetrics[selectedNode.id].sla_breach_count} SLA misses</span>
            </section>}
            {canManage && <button className="button secondary duplicate-button" onClick={duplicateSelectedNode}>Duplicate step</button>}
            <NodeAttachments projectId={projectId} nodeId={selectedNode.id} canManage={canManage}
              attachments={attachments.filter((attachment) => attachment.node_id === selectedNode.id)}
              onUpload={attachFile} onDelete={removeAttachment} />
          </> : <>
            <label>Branch label<input value={selectedEdge.label || ''} disabled={!canManage} placeholder="For example: Yes" onChange={(event) => updateSelectedEdge(event.target.value)} /></label>
            <label className="toggle-row">
              <span><strong>Bidirectional</strong><small>Show an arrow at both ends</small></span>
              <input type="checkbox" disabled={!canManage} checked={Boolean(selectedEdge.bidirectional)} onChange={(event) => toggleBidirectional(event.target.checked)} />
            </label>
            <div className="connection-detail">
              <span>From <strong>{selectedEdge.sourceHandle || 'auto'}</strong></span>
              <span>To <strong>{selectedEdge.targetHandle || 'auto'}</strong></span>
            </div>
          </>}
          {canManage && <button className="button delete-button" onClick={removeSelection}>Delete {selectedNode ? 'step' : 'connection'}</button>}
        </aside>}
      </section>
      <ProcessIntelligencePanel open={intelligenceOpen} onClose={() => setIntelligenceOpen(false)}
        projectId={projectId} nodes={nodes} canManage={canManage} analytics={processAnalytics}
        onAnalyticsChange={setProcessAnalytics}
        onSelectNode={(nodeId) => {
          setSelectedNodeId(nodeId); setSelectedNodeIds([nodeId]); setSelectedEdgeId(null);
          reactFlowRef.current?.fitView({ nodes: [{ id: nodeId }], padding: 1.4, duration: 220 });
        }} />
      <CollaborationPanel open={collaborationOpen} onClose={() => setCollaborationOpen(false)}
        currentUserId={user.id} currentUser={user} connected={collaborationStatus === 'connected'}
        tasks={projectTasks} onCreateTask={createProjectTask} onUpdateTask={updateProjectTask}
        deliverables={projectDeliverables} onCreateDeliverable={createProjectDeliverable}
        onUpdateDeliverable={updateProjectDeliverable}
        notes={projectNotes} contacts={communicationContacts} nodes={nodes} selectedNodeId={selectedNodeId}
        onSendNote={sendProjectNote} onResolveNote={resolveProjectNote} canManage={canManage} canComment={canComment}
        onSelectNode={(nodeId) => { setSelectedNodeId(nodeId); setSelectedEdgeId(null); }} />
      <ProjectDetailsDialog open={projectDetailsOpen} onClose={() => setProjectDetailsOpen(false)}
        onSave={saveProjectDetails} canManage={canManage} currentUser={user} currentUserAccess={projectAccess || 'viewer'}
        contacts={communicationContacts} projectId={projectId}
        description={projectDescription} status={projectStatus} ownerId={projectOwnerId}
        profile={projectProfile}
        collaboratorIds={projectCollaboratorIds} persisted={Boolean(projectId)}
        onGovernanceChange={(governance) => {
          setProjectAccess(governance.current_user_access);
          setProjectApprovalStatus(governance.approval_status);
          setProjectCollaboratorIds(governance.access_entries.map((entry) => entry.user.id));
        }}
        onRestored={hydrateRestoredProject} />
      <ClearCanvasDialog open={clearCanvasOpen} nodeCount={nodes.length} edgeCount={edges.length}
        onCancel={() => setClearCanvasOpen(false)} onConfirm={clearAll} />
    </main>
  );
}

function App() {
  const guestMatch = window.location.pathname.match(/^\/guest\/([^/]+)$/);
  return <ThemeProvider>{guestMatch
    ? <GuestPortal token={decodeURIComponent(guestMatch[1])} />
    : <AuthProvider><FlowForgeWorkspace /></AuthProvider>}</ThemeProvider>;
}

export default App;
