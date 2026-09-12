#!/usr/bin/env node

/**
 * AgentKit Diagram Deterministic Compiler (Node 18+ ESM)
 * Compiles typed JSON IR into deterministic SVG, trusted embeddable fragments, and self-contained HTML readers.
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT_DIR = resolve(__dirname, '../..');

const ID_REGEX = /^[a-zA-Z0-9_-]{1,64}$/;

function asciiCompare(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return 0;
  return a < b ? -1 : a > b ? 1 : 0;
}

function escapeXml(unsafe) {
  if (typeof unsafe !== 'string') return '';
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function serializeJsonForScript(data) {
  return JSON.stringify(data)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026');
}

function checkSafeText(val, name) {
  if (val !== undefined && val !== null) {
    if (typeof val !== 'string') {
      throw new Error(`Invalid IR: ${name} must be a string`);
    }
    if (val.length > 512) {
      throw new Error(`Invalid IR: ${name} exceeds maximum length of 512 characters`);
    }
  }
}

function parseArgs(args) {
  const options = {
    input: null,
    format: 'html', // 'svg' | 'fragment' | 'html'
    out: null,
    preset: null,
    theme: null
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--input' && i + 1 < args.length) {
      options.input = args[++i];
    } else if (arg === '--format' && i + 1 < args.length) {
      options.format = args[++i];
    } else if (arg === '--out' && i + 1 < args.length) {
      options.out = args[++i];
    } else if (arg === '--preset' && i + 1 < args.length) {
      options.preset = args[++i];
    } else if (arg === '--theme' && i + 1 < args.length) {
      options.theme = args[++i];
    }
  }

  const validFormats = ['svg', 'fragment', 'html'];
  if (!validFormats.includes(options.format)) {
    throw new Error(`Invalid --format "${options.format}". Must be one of ${validFormats.join(', ')}`);
  }

  const validPresets = ['classic', 'signal-flow', 'blueprint', 'editorial'];
  if (options.preset && !validPresets.includes(options.preset)) {
    throw new Error(`Invalid --preset "${options.preset}". Must be one of ${validPresets.join(', ')}`);
  }

  const validThemes = ['light', 'dark'];
  if (options.theme && !validThemes.includes(options.theme)) {
    throw new Error(`Invalid --theme "${options.theme}". Must be one of ${validThemes.join(', ')}`);
  }

  return options;
}

function validateIR(data) {
  if (!data || typeof data !== 'object') {
    throw new Error('Invalid IR: Root must be an object');
  }
  if (data.schema_version !== 1 && data.schemaVersion !== 1) {
    throw new Error('Invalid IR: schema_version must be 1');
  }
  const type = data.diagram_type || data.type;
  const validTypes = ['architecture', 'workflow', 'sequence', 'dataflow', 'lifecycle'];
  if (!validTypes.includes(type)) {
    throw new Error(`Invalid IR: unknown diagram_type "${type}". Must be one of ${validTypes.join(', ')}`);
  }
  if (!data.meta || typeof data.meta !== 'object') {
    throw new Error('Invalid IR: meta object is required');
  }
  if (!data.meta.title || typeof data.meta.title !== 'string') {
    throw new Error('Invalid IR: meta.title string is required');
  }
  checkSafeText(data.meta.title, 'meta.title');
  checkSafeText(data.meta.subtitle, 'meta.subtitle');
  checkSafeText(data.meta.description, 'meta.description');

  const validPresets = ['classic', 'signal-flow', 'blueprint', 'editorial'];
  if (data.meta.visual_preset && !validPresets.includes(data.meta.visual_preset)) {
    throw new Error(`Invalid IR: unknown visual_preset "${data.meta.visual_preset}". Must be one of ${validPresets.join(', ')}`);
  }
  const validThemes = ['light', 'dark'];
  if (data.meta.theme && !validThemes.includes(data.meta.theme)) {
    throw new Error(`Invalid IR: unknown theme "${data.meta.theme}". Must be one of ${validThemes.join(', ')}`);
  }

  const nodeIds = new Set();
  const checkId = (id, kind) => {
    if (!id || typeof id !== 'string') {
      throw new Error(`Invalid IR: ${kind} ID must be a non-empty string`);
    }
    if (!ID_REGEX.test(id)) {
      throw new Error(`Invalid IR: ${kind} ID "${id}" must match pattern ^[a-zA-Z0-9_-]{1,64}$`);
    }
    if (nodeIds.has(id)) {
      throw new Error(`Invalid IR: duplicate ID "${id}" in ${kind}`);
    }
    nodeIds.add(id);
  };

  const checkLabel = (item, kind) => {
    if (!item.label || typeof item.label !== 'string') {
      throw new Error(`Invalid IR: ${kind} "${item.id || 'unnamed'}" missing required string "label"`);
    }
    checkSafeText(item.label, `${kind}.label`);
    checkSafeText(item.description, `${kind}.description`);
  };

  if (type === 'architecture') {
    const components = data.components || [];
    if (!Array.isArray(components) || components.length === 0) {
      throw new Error('Invalid IR: architecture requires non-empty components array');
    }
    if (components.length > 250) {
      throw new Error('Invalid IR: architecture components exceed limit of 250');
    }
    const validRoles = ['frontend', 'backend', 'database', 'cache', 'queue', 'storage', 'gateway', 'auth', 'external', 'worker'];
    components.forEach(c => {
      checkId(c.id, 'component');
      checkLabel(c, 'component');
      if (c.role && !validRoles.includes(c.role)) {
        throw new Error(`Invalid IR: component "${c.id}" has invalid role "${c.role}". Must be one of ${validRoles.join(', ')}`);
      }
    });

    const connections = data.connections || [];
    if (connections.length > 1000) {
      throw new Error('Invalid IR: connections exceed limit of 1000');
    }
    connections.forEach((conn, idx) => {
      if (conn.id) checkSafeText(conn.id, `connections[${idx}].id`);
      checkSafeText(conn.label, `connections[${idx}].label`);
      checkSafeText(conn.protocol, `connections[${idx}].protocol`);
      if (!conn.from || !nodeIds.has(conn.from)) {
        throw new Error(`Invalid IR: dangling connection "from" endpoint "${conn.from}" at index ${idx}`);
      }
      if (!conn.to || !nodeIds.has(conn.to)) {
        throw new Error(`Invalid IR: dangling connection "to" endpoint "${conn.to}" at index ${idx}`);
      }
    });
  } else if (type === 'workflow') {
    const steps = data.steps || [];
    if (!Array.isArray(steps) || steps.length === 0) {
      throw new Error('Invalid IR: workflow requires non-empty steps array');
    }
    if (steps.length > 250) {
      throw new Error('Invalid IR: workflow steps exceed limit of 250');
    }
    const validKinds = ['start', 'action', 'decision', 'wait', 'subprocess', 'terminal-success', 'terminal-failure'];
    steps.forEach(s => {
      checkId(s.id, 'step');
      checkLabel(s, 'step');
      if (s.kind && !validKinds.includes(s.kind)) {
        throw new Error(`Invalid IR: step "${s.id}" has invalid kind "${s.kind}". Must be one of ${validKinds.join(', ')}`);
      }
    });

    const transitions = data.transitions || [];
    if (transitions.length > 1000) {
      throw new Error('Invalid IR: transitions exceed limit of 1000');
    }
    transitions.forEach((t, idx) => {
      if (t.id) checkSafeText(t.id, `transitions[${idx}].id`);
      checkSafeText(t.label, `transitions[${idx}].label`);
      checkSafeText(t.condition, `transitions[${idx}].condition`);
      if (!t.from || !nodeIds.has(t.from)) {
        throw new Error(`Invalid IR: dangling transition "from" endpoint "${t.from}" at index ${idx}`);
      }
      if (!t.to || !nodeIds.has(t.to)) {
        throw new Error(`Invalid IR: dangling transition "to" endpoint "${t.to}" at index ${idx}`);
      }
    });
  } else if (type === 'sequence') {
    const participants = data.participants || [];
    if (!Array.isArray(participants) || participants.length === 0) {
      throw new Error('Invalid IR: sequence requires non-empty participants array');
    }
    if (participants.length > 50) {
      throw new Error('Invalid IR: sequence participants exceed limit of 50');
    }
    participants.forEach(p => {
      checkId(p.id, 'participant');
      checkLabel(p, 'participant');
    });

    const messages = data.messages || [];
    if (messages.length > 500) {
      throw new Error('Invalid IR: sequence messages exceed limit of 500');
    }
    const validMsgKinds = ['sync-call', 'async-signal', 'return', 'self-call', 'error'];
    messages.forEach((m, idx) => {
      if (!m.label || typeof m.label !== 'string') {
        throw new Error(`Invalid IR: message at index ${idx} missing required string "label"`);
      }
      checkSafeText(m.label, `messages[${idx}].label`);
      if (m.kind && !validMsgKinds.includes(m.kind)) {
        throw new Error(`Invalid IR: message at index ${idx} has invalid kind "${m.kind}"`);
      }
      if (!m.from || !nodeIds.has(m.from)) {
        throw new Error(`Invalid IR: dangling message "from" endpoint "${m.from}" at index ${idx}`);
      }
      if (!m.to || !nodeIds.has(m.to)) {
        throw new Error(`Invalid IR: dangling message "to" endpoint "${m.to}" at index ${idx}`);
      }
    });
  } else if (type === 'dataflow') {
    const nodes = data.nodes || [];
    if (!Array.isArray(nodes) || nodes.length === 0) {
      throw new Error('Invalid IR: dataflow requires non-empty nodes array');
    }
    if (nodes.length > 250) {
      throw new Error('Invalid IR: dataflow nodes exceed limit of 250');
    }
    const validRoles = ['source', 'transform', 'store', 'sink', 'consumer', 'filter', 'governance'];
    nodes.forEach(n => {
      checkId(n.id, 'dataflow node');
      checkLabel(n, 'dataflow node');
      if (n.role && !validRoles.includes(n.role)) {
        throw new Error(`Invalid IR: dataflow node "${n.id}" has invalid role "${n.role}"`);
      }
    });

    const flows = data.flows || [];
    if (flows.length > 1000) {
      throw new Error('Invalid IR: dataflow flows exceed limit of 1000');
    }
    flows.forEach((f, idx) => {
      checkSafeText(f.label, `flows[${idx}].label`);
      checkSafeText(f.schema_type, `flows[${idx}].schema_type`);
      if (!f.from || !nodeIds.has(f.from)) {
        throw new Error(`Invalid IR: dangling flow "from" endpoint "${f.from}" at index ${idx}`);
      }
      if (!f.to || !nodeIds.has(f.to)) {
        throw new Error(`Invalid IR: dangling flow "to" endpoint "${f.to}" at index ${idx}`);
      }
    });
  } else if (type === 'lifecycle') {
    const states = data.states || [];
    if (!Array.isArray(states) || states.length === 0) {
      throw new Error('Invalid IR: lifecycle requires non-empty states array');
    }
    if (states.length > 250) {
      throw new Error('Invalid IR: lifecycle states exceed limit of 250');
    }
    const validKinds = ['initial', 'active', 'waiting', 'failure-recoverable', 'failure-fatal', 'terminal-success', 'terminal-cancelled'];
    states.forEach(s => {
      checkId(s.id, 'state');
      checkLabel(s, 'state');
      if (s.kind && !validKinds.includes(s.kind)) {
        throw new Error(`Invalid IR: state "${s.id}" has invalid kind "${s.kind}"`);
      }
    });

    const transitions = data.transitions || [];
    if (transitions.length > 1000) {
      throw new Error('Invalid IR: lifecycle transitions exceed limit of 1000');
    }
    transitions.forEach((t, idx) => {
      checkSafeText(t.event, `transitions[${idx}].event`);
      checkSafeText(t.action, `transitions[${idx}].action`);
      if (!t.from || !nodeIds.has(t.from)) {
        throw new Error(`Invalid IR: dangling lifecycle transition "from" endpoint "${t.from}" at index ${idx}`);
      }
      if (!t.to || !nodeIds.has(t.to)) {
        throw new Error(`Invalid IR: dangling lifecycle transition "to" endpoint "${t.to}" at index ${idx}`);
      }
    });
  }

  if (data.meta.views && Array.isArray(data.meta.views)) {
    if (data.meta.views.length > 5) {
      throw new Error('Invalid IR: views/chapters exceed maximum limit of 5');
    }
    data.meta.views.forEach((v, vIdx) => {
      checkSafeText(v.title, `views[${vIdx}].title`);
      checkSafeText(v.narrative, `views[${vIdx}].narrative`);
      if (v.focus_nodes && Array.isArray(v.focus_nodes)) {
        v.focus_nodes.forEach(fn => {
          if (!nodeIds.has(fn)) {
            throw new Error(`Invalid IR: view "${v.id || vIdx}" references non-existent focus node "${fn}"`);
          }
        });
      }
      if (v.highlight_route && Array.isArray(v.highlight_route)) {
        v.highlight_route.forEach(rn => {
          if (!nodeIds.has(rn)) {
            throw new Error(`Invalid IR: view "${v.id || vIdx}" references non-existent route node "${rn}"`);
          }
        });
      }
    });
  }

  return type;
}

function layoutArchitecture(data) {
  const components = data.components || [];
  const connections = data.connections || [];
  const boundaries = data.boundaries || [];

  const layers = new Map();
  components.forEach(comp => {
    const l = comp.layer !== undefined ? comp.layer : 0;
    if (!layers.has(l)) layers.set(l, []);
    layers.get(l).push(comp);
  });

  const sortedLayers = Array.from(layers.keys()).sort((a, b) => a - b);
  const nodePositions = new Map();

  const nodeWidth = 160;
  const nodeHeight = 64;
  const layerGapX = 100;
  const nodeGapY = 40;

  let startX = 60;
  let maxH = 0;

  sortedLayers.forEach(l => {
    const compList = layers.get(l);
    compList.sort((a, b) => asciiCompare(a.id, b.id));
    let startY = 80;

    compList.forEach((comp, idx) => {
      const x = startX;
      const y = startY + idx * (nodeHeight + nodeGapY);
      nodePositions.set(comp.id, { x, y, width: nodeWidth, height: nodeHeight, comp });
      if (y + nodeHeight > maxH) maxH = y + nodeHeight;
    });

    startX += nodeWidth + layerGapX;
  });

  // Layout Boundaries (Calculate enclosing bounding boxes)
  const renderedBoundaries = [];
  boundaries.forEach(b => {
    const bComps = (b.components || []).map(id => nodePositions.get(id)).filter(Boolean);
    if (bComps.length > 0) {
      const minX = Math.min(...bComps.map(p => p.x)) - 16;
      const minY = Math.min(...bComps.map(p => p.y)) - 28;
      const maxX = Math.max(...bComps.map(p => p.x + p.width)) + 16;
      const maxY = Math.max(...bComps.map(p => p.y + p.height)) + 16;
      renderedBoundaries.push({
        id: b.id,
        label: b.label,
        role: b.role,
        x: minX,
        y: minY,
        width: maxX - minX,
        height: maxY - minY
      });
    }
  });

  const totalWidth = Math.max(startX + 40, 700);
  const totalHeight = Math.max(maxH + 80, 420);

  return { nodePositions, connections, boundaries: renderedBoundaries, totalWidth, totalHeight, components };
}

function layoutWorkflow(data) {
  const steps = data.steps || [];
  const transitions = data.transitions || [];
  const lanes = data.lanes || [];

  const laneMap = new Map();
  if (lanes.length === 0) {
    laneMap.set('default', { id: 'default', label: 'Main Process', steps: [] });
  } else {
    lanes.forEach(l => laneMap.set(l.id, { ...l, steps: [] }));
  }

  steps.forEach(s => {
    const laneId = s.lane && laneMap.has(s.lane) ? s.lane : (lanes[0] ? lanes[0].id : 'default');
    if (laneMap.has(laneId)) laneMap.get(laneId).steps.push(s);
  });

  const nodePositions = new Map();
  const renderedLanes = [];
  const stepWidth = 150;
  const stepHeight = 56;
  let currentY = 80;
  let maxW = 0;

  Array.from(laneMap.values()).forEach((lane) => {
    let currentX = 240;
    const startY = currentY;
    lane.steps.forEach((st) => {
      nodePositions.set(st.id, { x: currentX, y: currentY, width: stepWidth, height: stepHeight, comp: st });
      currentX += stepWidth + 60;
      if (currentX > maxW) maxW = currentX;
    });

    const laneHeight = stepHeight + 40;
    renderedLanes.push({
      id: lane.id,
      label: lane.label,
      role: lane.role,
      x: 40,
      y: startY - 16,
      width: Math.max(currentX, 600),
      height: laneHeight
    });
    currentY += laneHeight + 30;
  });

  return { nodePositions, connections: transitions, lanes: renderedLanes, boundaries: [], totalWidth: Math.max(maxW + 40, 700), totalHeight: Math.max(currentY + 40, 400), components: steps };
}

function layoutSequence(data) {
  const participants = data.participants || [];
  const messages = data.messages || [];

  const nodePositions = new Map();
  const participantWidth = 130;
  const participantHeight = 48;
  const gapX = 140;
  let currentX = 60;

  participants.forEach(p => {
    nodePositions.set(p.id, { x: currentX, y: 50, width: participantWidth, height: participantHeight, comp: p });
    currentX += participantWidth + gapX;
  });

  const totalWidth = Math.max(currentX + 40, 700);
  const startY = 140;
  const msgGapY = 50;
  const totalHeight = Math.max(startY + messages.length * msgGapY + 80, 400);

  return { nodePositions, messages, participants, totalWidth, totalHeight, startY, msgGapY };
}

function layoutDataflow(data) {
  const nodes = data.nodes || [];
  const flows = data.flows || [];
  const stages = data.stages || [];

  const stageMap = new Map();
  stages.forEach(st => stageMap.set(st.id, { ...st, nodes: [] }));

  nodes.forEach(n => {
    if (n.stage && stageMap.has(n.stage)) {
      stageMap.get(n.stage).nodes.push(n);
    } else {
      if (!stageMap.has('default')) stageMap.set('default', { id: 'default', label: 'Processing', nodes: [] });
      stageMap.get('default').nodes.push(n);
    }
  });

  const nodePositions = new Map();
  const renderedStages = [];
  const nodeW = 150;
  const nodeH = 56;
  let startX = 60;
  let maxH = 0;

  Array.from(stageMap.values()).forEach((st) => {
    let startY = 100;
    const stageStartX = startX;
    st.nodes.forEach((n, idx) => {
      const y = startY + idx * (nodeH + 40);
      nodePositions.set(n.id, { x: startX, y, width: nodeW, height: nodeH, comp: n });
      if (y + nodeH > maxH) maxH = y + nodeH;
    });

    renderedStages.push({
      id: st.id,
      label: st.label,
      x: stageStartX - 12,
      y: 60,
      width: nodeW + 24,
      height: Math.max(st.nodes.length * (nodeH + 40) + 60, 200)
    });

    startX += nodeW + 90;
  });

  return { nodePositions, connections: flows, stages: renderedStages, boundaries: [], totalWidth: Math.max(startX + 40, 700), totalHeight: Math.max(maxH + 80, 400), components: nodes };
}

function layoutLifecycle(data) {
  const states = data.states || [];
  const transitions = data.transitions || [];

  const nodePositions = new Map();
  const stateW = 140;
  const stateH = 50;
  let currentX = 60;
  let currentY = 90;
  let maxW = 0;

  states.forEach((st, idx) => {
    if (idx > 0 && idx % 3 === 0) {
      currentX = 60;
      currentY += stateH + 70;
    }
    nodePositions.set(st.id, { x: currentX, y: currentY, width: stateW, height: stateH, comp: st });
    currentX += stateW + 80;
    if (currentX > maxW) maxW = currentX;
  });

  return { nodePositions, connections: transitions, boundaries: [], totalWidth: Math.max(maxW + 40, 700), totalHeight: Math.max(currentY + stateH + 80, 400), components: states };
}

function renderSVG(type, layout, data, preset, theme, instanceId, isStandaloneSvg) {
  const { totalWidth, totalHeight } = layout;
  let svgContent = `<svg class="ak-diagram-svg" viewBox="0 0 ${totalWidth} ${totalHeight}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeXml(data.meta.title)}">`;
  svgContent += `<title>${escapeXml(data.meta.title)}</title>`;
  if (data.meta.description) {
    svgContent += `<desc>${escapeXml(data.meta.description)}</desc>`;
  }

  const arrowMarkerId = `ak-arrowhead-${instanceId}`;

  // Defs: Markers & Embedded CSS ONLY for standalone SVG portability
  svgContent += `<defs>`;
  if (isStandaloneSvg) {
    svgContent += `<style>
      svg {
        --ak-bg: #ffffff; --ak-surface: #f8fafc; --ak-surface-border: #e2e8f0;
        --ak-text-primary: #0f172a; --ak-text-secondary: #475569; --ak-text-muted: #94a3b8;
        --ak-accent: #2563eb; --ak-node-bg: #ffffff; --ak-node-border: #cbd5e1;
        --ak-edge-stroke: #64748b; --ak-edge-active: #2563eb;
        --ak-font-sans: system-ui, -apple-system, sans-serif;
        font-family: var(--ak-font-sans);
      }
      ${theme === 'dark' ? `svg { --ak-bg: #090d16; --ak-text-primary: #f8fafc; --ak-text-secondary: #94a3b8; --ak-node-bg: #0f172a; --ak-node-border: #334155; --ak-edge-stroke: #475569; --ak-edge-active: #38bdf8; }` : ''}
      ${preset === 'signal-flow' ? `svg { --ak-accent: #06b6d4; --ak-edge-stroke: #0ea5e9; --ak-edge-active: #38bdf8; }` : ''}
      ${preset === 'blueprint' ? `svg { --ak-bg: #0f2744; --ak-text-primary: #e0f2fe; --ak-node-bg: #0c213a; --ak-node-border: #38bdf8; --ak-edge-stroke: #7dd3fc; }` : ''}
      ${preset === 'editorial' ? `svg { --ak-bg: #faf8f5; --ak-text-primary: #1c1917; --ak-accent: #991b1b; --ak-node-border: #d6cfc4; --ak-edge-stroke: #78716c; }` : ''}
    </style>`;
  }
  svgContent += `<marker id="${arrowMarkerId}" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="var(--ak-edge-stroke)" />
    </marker>
  </defs>`;

  // Render Boundaries (Architecture)
  if (layout.boundaries && layout.boundaries.length > 0) {
    layout.boundaries.forEach(b => {
      svgContent += `<g class="ak-boundary" data-boundary-id="${escapeXml(b.id)}">
        <rect x="${b.x}" y="${b.y}" width="${b.width}" height="${b.height}" rx="12" fill="none" stroke="var(--ak-surface-border)" stroke-width="1.5" stroke-dasharray="6 4" />
        <text x="${b.x + 12}" y="${b.y + 18}" font-size="11" font-weight="600" fill="var(--ak-text-muted)" font-family="var(--ak-font-sans)">${escapeXml(b.label)}</text>
      </g>`;
    });
  }

  // Render Lanes (Workflow)
  if (layout.lanes && layout.lanes.length > 0) {
    layout.lanes.forEach(l => {
      svgContent += `<g class="ak-lane" data-lane-id="${escapeXml(l.id)}">
        <rect x="${l.x}" y="${l.y}" width="${l.width}" height="${l.height}" rx="8" fill="var(--ak-surface)" stroke="var(--ak-surface-border)" stroke-width="1" />
        <text x="${l.x + 12}" y="${l.y + 32}" font-size="12" font-weight="700" fill="var(--ak-text-secondary)" font-family="var(--ak-font-sans)">${escapeXml(l.label)}</text>
      </g>`;
    });
  }

  // Render Stages (Dataflow)
  if (layout.stages && layout.stages.length > 0) {
    layout.stages.forEach(st => {
      svgContent += `<g class="ak-stage" data-stage-id="${escapeXml(st.id)}">
        <rect x="${st.x}" y="${st.y}" width="${st.width}" height="${st.height}" rx="8" fill="var(--ak-surface)" stroke="var(--ak-surface-border)" stroke-width="1" stroke-dasharray="4 2" />
        <text x="${st.x + st.width / 2}" y="${st.y + 20}" font-size="11" font-weight="600" fill="var(--ak-text-muted)" text-anchor="middle" font-family="var(--ak-font-sans)">${escapeXml(st.label)}</text>
      </g>`;
    });
  }

  if (type === 'sequence') {
    const { nodePositions, messages, participants, startY, msgGapY } = layout;

    // Lifelines
    participants.forEach(p => {
      const pos = nodePositions.get(p.id);
      const centerX = pos.x + pos.width / 2;
      svgContent += `<line x1="${centerX}" y1="${pos.y + pos.height}" x2="${centerX}" y2="${totalHeight - 40}" stroke="var(--ak-edge-stroke)" stroke-width="1.5" stroke-dasharray="4 4" opacity="0.6" />`;
    });

    // Messages
    messages.forEach((msg, idx) => {
      const pFrom = nodePositions.get(msg.from);
      const pTo = nodePositions.get(msg.to);
      if (!pFrom || !pTo) return;

      const y = startY + idx * msgGapY;
      const x1 = pFrom.x + pFrom.width / 2;
      const x2 = pTo.x + pTo.width / 2;
      const isReturn = msg.kind === 'return';

      svgContent += `<g class="ak-edge" data-from="${escapeXml(msg.from)}" data-to="${escapeXml(msg.to)}" data-edge-id="${escapeXml(msg.id || `msg-${idx}`)}">
        <line x1="${x1}" y1="${y}" x2="${x2}" y2="${y}" stroke="var(--ak-edge-stroke)" stroke-width="2" ${isReturn ? 'stroke-dasharray="5 3"' : ''} marker-end="url(#${arrowMarkerId})" />
        <text x="${(x1 + x2) / 2}" y="${y - 6}" font-size="11" fill="var(--ak-text-secondary)" text-anchor="middle" font-family="var(--ak-font-sans)">${escapeXml(msg.label)}</text>
      </g>`;
    });

    // Participant Boxes
    participants.forEach(p => {
      const pos = nodePositions.get(p.id);
      const desc = p.description || p.role || '';
      svgContent += `<g class="ak-node" data-node-id="${escapeXml(p.id)}" data-label="${escapeXml(p.label)}" data-role="${escapeXml(p.role || 'service')}" data-desc="${escapeXml(desc)}" tabindex="0">
        <rect x="${pos.x}" y="${pos.y}" width="${pos.width}" height="${pos.height}" rx="6" fill="var(--ak-node-bg)" stroke="var(--ak-node-border)" stroke-width="1.5" />
        <text x="${pos.x + pos.width / 2}" y="${pos.y + pos.height / 2 + 4}" font-size="13" font-weight="600" fill="var(--ak-text-primary)" text-anchor="middle" font-family="var(--ak-font-sans)">${escapeXml(p.label)}</text>
      </g>`;
    });

  } else {
    const { nodePositions, connections, components } = layout;

    // Render Connections
    connections.forEach((conn, idx) => {
      const pFrom = nodePositions.get(conn.from);
      const pTo = nodePositions.get(conn.to);
      if (!pFrom || !pTo) return;

      const x1 = pFrom.x + pFrom.width;
      const y1 = pFrom.y + pFrom.height / 2;
      const x2 = pTo.x;
      const y2 = pTo.y + pTo.height / 2;

      const edgeId = conn.id || `edge-${conn.from}-${conn.to}-${idx}`;
      const dx = Math.max(Math.abs(x2 - x1) / 2, 40);
      const pathD = (x2 >= x1)
        ? `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
        : `M ${x1} ${y1} C ${x1 + 60} ${y1 + 40}, ${x2 - 60} ${y2 + 40}, ${x2} ${y2}`;

      svgContent += `<g class="ak-edge" data-from="${escapeXml(conn.from)}" data-to="${escapeXml(conn.to)}" data-edge-id="${escapeXml(edgeId)}">
        <path d="${pathD}" fill="none" stroke="var(--ak-edge-stroke)" stroke-width="2" marker-end="url(#${arrowMarkerId})" />`;
      if (conn.label || conn.event) {
        const lbl = conn.label || conn.event;
        svgContent += `<text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 6}" font-size="10" font-weight="500" fill="var(--ak-text-secondary)" text-anchor="middle" font-family="var(--ak-font-sans)" style="stroke:none;stroke-width:0;">${escapeXml(lbl)}</text>`;
      }
      svgContent += `</g>`;
    });

    // Render Nodes
    components.forEach(comp => {
      const pos = nodePositions.get(comp.id);
      if (!pos) return;
      const role = comp.role || comp.kind || 'node';
      const desc = comp.description || '';

      svgContent += `<g class="ak-node" data-node-id="${escapeXml(comp.id)}" data-label="${escapeXml(comp.label)}" data-role="${escapeXml(role)}" data-desc="${escapeXml(desc)}" tabindex="0">
        <rect x="${pos.x}" y="${pos.y}" width="${pos.width}" height="${pos.height}" rx="8" fill="var(--ak-node-bg)" stroke="var(--ak-node-border)" stroke-width="1.5" />
        <text x="${pos.x + pos.width / 2}" y="${pos.y + 24}" font-size="12" font-weight="600" fill="var(--ak-text-primary)" text-anchor="middle" font-family="var(--ak-font-sans)">${escapeXml(comp.label)}</text>
        <text x="${pos.x + pos.width / 2}" y="${pos.y + 42}" font-size="10" fill="var(--ak-text-muted)" text-anchor="middle" font-family="var(--ak-font-sans)">${escapeXml(role)}</text>
      </g>`;
    });
  }

  svgContent += `</svg>`;
  return svgContent;
}

function compile(rawJson, options = {}) {
  const data = typeof rawJson === 'string' ? JSON.parse(rawJson) : rawJson;
  const type = validateIR(data);

  const preset = options.preset || (data.meta && data.meta.visual_preset) || 'classic';
  const theme = options.theme || (data.meta && data.meta.theme) || 'light';
  const anim = (data.meta && data.meta.animation) || 'none';
  const instanceId = createHash('sha256').update(JSON.stringify(data)).digest('hex').slice(0, 8);
  const isStandaloneSvg = options.format === 'svg';

  let layout;
  if (type === 'architecture') layout = layoutArchitecture(data);
  else if (type === 'workflow') layout = layoutWorkflow(data);
  else if (type === 'sequence') layout = layoutSequence(data);
  else if (type === 'dataflow') layout = layoutDataflow(data);
  else if (type === 'lifecycle') layout = layoutLifecycle(data);

  const svg = renderSVG(type, layout, data, preset, theme, instanceId, isStandaloneSvg);

  if (options.format === 'svg') {
    return svg;
  }

  const readerCss = readFileSync(join(ROOT_DIR, 'assets/reader.css'), 'utf-8');
  const readerJs = readFileSync(join(ROOT_DIR, 'assets/reader.js'), 'utf-8');

  const subtitleHtml = data.meta && data.meta.subtitle ? `<span class="ak-diagram-subtitle"> — ${escapeXml(data.meta.subtitle)}</span>` : '';
  const hasViews = data.meta && data.meta.views && data.meta.views.length > 0;
  const chapterControl = hasViews ? `<div class="ak-chapter-controls">
    <button type="button" class="ak-diagram-btn ak-btn-prev-chapter" title="Previous Chapter ([)">‹</button>
    <span class="ak-chapter-label">1/${data.meta.views.length}</span>
    <button type="button" class="ak-diagram-btn ak-btn-next-chapter" title="Next Chapter (])">›</button>
  </div>` : '';

  // Scoped Fragment
  const fragment = `<div class="ak-diagram-root" data-instance-id="${instanceId}" data-preset="${escapeXml(preset)}" data-theme="${escapeXml(theme)}" data-animation="${escapeXml(anim)}">
    <style>${readerCss}</style>
    <div class="ak-diagram-toolbar">
      <h4 class="ak-diagram-title"><span>📊</span> ${escapeXml(data.meta.title)}${subtitleHtml}</h4>
      <div class="ak-diagram-controls">
        <input type="text" class="ak-diagram-search-input" placeholder="Search (/) ..." aria-label="Search diagram nodes and descriptions" />
        <button type="button" class="ak-diagram-btn ak-btn-reach-down" title="Downstream Reach">↓ Reach</button>
        <button type="button" class="ak-diagram-btn ak-btn-reach-up" title="Upstream Reach">↑ Reach</button>
        <button type="button" class="ak-diagram-btn ak-btn-route" title="Route Inspection (R)">📍 Route</button>
        <button type="button" class="ak-diagram-btn ak-btn-lens" title="Role Lens (L)">🔍 Lens</button>
        ${chapterControl}
        <button type="button" class="ak-diagram-btn ak-btn-theme" title="Toggle Light/Dark">${theme === 'dark' ? '☀️' : '🌙'}</button>
        <button type="button" class="ak-diagram-btn ak-btn-present" title="Presentation Stage (F)">⛶</button>
        <button type="button" class="ak-diagram-btn ak-btn-share" title="Export 1200x630 Share Card">📤 Card</button>
      </div>
    </div>
    <div class="ak-diagram-viewport">
      ${svg}
    </div>
    <script type="application/json" class="ak-diagram-data">${serializeJsonForScript(data)}</script>
    <script>${readerJs}</script>
  </div>`;

  if (options.format === 'fragment') {
    return fragment;
  }

  return `<!DOCTYPE html>
<html lang="${escapeXml(data.meta.locale || 'en')}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeXml(data.meta.title)}</title>
  <style>
    body {
      margin: 0;
      padding: 24px;
      background: #f1f5f9;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      box-sizing: border-box;
    }
  </style>
</head>
<body>
  ${fragment}
</body>
</html>`;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    const options = parseArgs(process.argv.slice(2));
    if (!options.input) {
      console.error('Usage: node compile.mjs --input <diagram.json> [--format svg|fragment|html] [--out <output_path>] [--preset <preset>] [--theme <light|dark>]');
      process.exit(1);
    }

    const raw = readFileSync(options.input, 'utf-8');
    const output = compile(raw, options);

    if (options.out) {
      mkdirSync(dirname(resolve(options.out)), { recursive: true });
      writeFileSync(options.out, output, 'utf-8');
      console.log(`Successfully compiled to ${options.out}`);
    } else {
      process.stdout.write(output);
    }
  } catch (err) {
    console.error(`Compilation Error: ${err.message}`);
    process.exit(1);
  }
}

export { compile, validateIR };
