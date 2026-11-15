import React from 'react';

export default function WorkflowReturn({ stage }) {
  function back(event) {
    const current = event.currentTarget.closest('dialog');
    const workflow = document.getElementById('landslide-workspace');
    if (!workflow) return;
    current?.close();
    if (!workflow.open) workflow.showModal();
  }
  return <div className="workflow-return">
    <button className="quiet" type="button" onClick={back}>
      ← Landslide workflow
    </button>
    <span className="workflow-stage-note">{stage}</span>
  </div>;
}
