import React from 'react';
import { DIAGRAM_LIBRARY, DiagramSymbol } from './DiagramSymbols';

export default function DiagramLibrary({ open, onClose, onAdd }) {
  if (!open) return null;
  return <div className="diagram-library" role="dialog" aria-label="Diagram objects">
    <header><span><strong>Add to canvas</strong><small>Shapes, BPMN, and enterprise symbols</small></span>
      <button aria-label="Close diagram objects" onClick={onClose}>×</button></header>
    <div>{DIAGRAM_LIBRARY.map((category) => <section key={category.id}>
      <h3>{category.label}</h3>
      <div>{category.items.map((item) => <button key={item.id} onClick={() => onAdd(item)}
        aria-label={`Add ${item.label}`} title={item.label}>
        <span className={`library-symbol shape-${item.shape}`}><DiagramSymbol symbol={item.symbol} />
          {!item.symbol && <i>{item.shape === 'text' ? 'T' : item.shape === 'diamond' ? '◇' : item.shape === 'document' ? '▤' : item.shape === 'ellipse' ? '○' : '□'}</i>}</span>
        <small>{item.label}</small>
      </button>)}</div>
    </section>)}</div>
  </div>;
}
