import React, { useRef, useState } from 'react';
import { attachmentDownloadUrl } from './attachmentService';

function fileSize(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function NodeAttachments({ projectId, nodeId, attachments = [], canManage, onUpload, onDelete }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selectFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError('Files must be 10 MB or smaller.');
      return;
    }
    setBusy(true); setError('');
    try {
      await onUpload(file, nodeId);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (attachment) => {
    if (!window.confirm(`Remove ${attachment.filename}?`)) return;
    setBusy(true); setError('');
    try {
      await onDelete(attachment.id);
    } catch (deleteError) {
      setError(deleteError.message);
    } finally {
      setBusy(false);
    }
  };
  return <section className="node-attachments">
    <header><span><strong>Attachments</strong><small>{attachments.length} linked to this step</small></span>
      {canManage && projectId && <><input ref={inputRef} aria-label="Attach file to step" type="file" onChange={selectFile} />
        <button type="button" disabled={busy} onClick={() => inputRef.current?.click()}>{busy ? 'Uploading…' : '＋ Add file'}</button></>}
    </header>
    {!projectId && canManage && <p>Save this workflow before attaching files.</p>}
    {projectId && attachments.length === 0 && <p>No files attached to this step.</p>}
    {attachments.length > 0 && <div>{attachments.map((attachment) => <article key={attachment.id}>
      <span>{(attachment.scan_status || 'clean') === 'clean' ? '↗' : '…'}</span>
      {(attachment.scan_status || 'clean') === 'clean'
        ? <a href={attachmentDownloadUrl(projectId, attachment.id)}>{attachment.filename}<small>{fileSize(attachment.size_bytes)}</small></a>
        : <span className="attachment-pending">{attachment.filename}<small>{attachment.scan_status === 'blocked' ? 'Blocked by security scan' : 'Security scan pending'}</small></span>}
      {canManage && <button type="button" disabled={busy} aria-label={`Remove ${attachment.filename}`} onClick={() => remove(attachment)}>×</button>}
    </article>)}</div>}
    {error && <em role="alert">{error}</em>}
  </section>;
}
