import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { API_BASE_URL } from './apiClient';
import { createProjectArtifact } from './flowchartService';


export default function ProjectExportMenu({ projectId, canManage, onExportPng }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [menuPosition, setMenuPosition] = useState(null);
  const rootRef = useRef(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const positionMenu = () => {
      const bounds = rootRef.current?.getBoundingClientRect();
      if (!bounds) return;
      const width = Math.min(330, window.innerWidth - 32);
      setMenuPosition({
        left: Math.max(16, Math.min(bounds.right - width, window.innerWidth - width - 16)),
        top: bounds.bottom + 10,
        width,
      });
    };
    const close = (event) => {
      if (
        event.key === 'Escape'
        || (!rootRef.current?.contains(event.target) && !menuRef.current?.contains(event.target))
      ) setOpen(false);
    };
    positionMenu();
    document.addEventListener('keydown', close);
    document.addEventListener('mousedown', close);
    window.addEventListener('resize', positionMenu);
    window.addEventListener('scroll', positionMenu, true);
    return () => {
      document.removeEventListener('keydown', close);
      document.removeEventListener('mousedown', close);
      window.removeEventListener('resize', positionMenu);
      window.removeEventListener('scroll', positionMenu, true);
    };
  }, [open]);

  useEffect(() => {
    if (!notice) return undefined;
    const timeout = window.setTimeout(() => setNotice(''), 3200);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  const download = async (kind, format) => {
    if (!projectId) return;
    setBusy(`${kind}:${format}`);
    setError('');
    try {
      const artifact = await createProjectArtifact(projectId, { kind, format });
      const link = document.createElement('a');
      link.href = artifact.download_url.startsWith('http')
        ? artifact.download_url
        : `${API_BASE_URL}${artifact.download_url}`;
      link.download = artifact.filename || `flowchart.${format}`;
      link.rel = 'noopener';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setNotice(`${artifact.filename || format.toUpperCase()} download started.`);
      setOpen(false);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy('');
    }
  };

  const runPng = async () => {
    setBusy('png');
    setError('');
    try {
      const filename = await onExportPng();
      setNotice(`${filename || 'PNG image'} download started.`);
      setOpen(false);
    } catch (requestError) {
      setError(requestError.message || 'The PNG image could not be exported.');
    } finally {
      setBusy('');
    }
  };

  const menu = open && menuPosition && <div className="project-export-menu" ref={menuRef}
    role="menu" aria-label="Export options" style={menuPosition}>
    <button role="menuitem" onClick={runPng} disabled={Boolean(busy)}>
      <strong>{busy === 'png' ? 'Preparing PNG…' : 'PNG image'}</strong>
      <span>Capture the current canvas instantly</span>
    </button>
    <button role="menuitem" onClick={() => download('export', 'svg')}
      disabled={!projectId || Boolean(busy)}>
      <strong>{busy === 'export:svg' ? 'Preparing SVG…' : 'SVG diagram'}</strong>
      <span>Scalable, queued server export</span>
    </button>
    <button role="menuitem" onClick={() => download('export', 'json')}
      disabled={!projectId || Boolean(busy)}>
      <strong>{busy === 'export:json' ? 'Preparing JSON…' : 'JSON backup'}</strong>
      <span>Portable project and graph data</span>
    </button>
    {canManage && <button role="menuitem" onClick={() => download('evidence_package', 'zip')}
      disabled={!projectId || Boolean(busy)}>
      <strong>{busy === 'evidence_package:zip' ? 'Building package…' : 'Evidence package'}</strong>
      <span>ZIP with revisions, approvals, audit, and plan records</span>
    </button>}
    {canManage && <button role="menuitem" onClick={() => download('operational_package', 'zip')}
      disabled={!projectId || Boolean(busy)}>
      <strong>{busy === 'operational_package:zip' ? 'Building documents…' : 'Operating documents'}</strong>
      <span>SOP, RACI, checklist, controls, training, and tests</span>
    </button>}
    {!projectId && <small>Save the workflow before creating server exports.</small>}
    {error && <p className="project-export-error" role="alert">{error}</p>}
  </div>;

  return <>
    <div className="project-export" ref={rootRef}>
      <button className={`tool-button ${open ? 'active' : ''}`} aria-label="Export PNG or project package"
        aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        Export ▾
      </button>
    </div>
    {menu && createPortal(menu, document.body)}
    {notice && createPortal(
      <div className="project-export-toast" role="status">✓ {notice}</div>,
      document.body,
    )}
  </>;
}
