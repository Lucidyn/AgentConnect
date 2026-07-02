/**
 * Visual DAG composer — drag nodes, click-to-connect ports, inspector panel.
 */
import { apiFetch } from './api.js';

const NODE_W = 132;
  const NODE_H = 56;
  const AGENT_COLORS = {
    Research: '#3b82f6',
    Coder: '#10b981',
    Writer: '#06b6d4',
    Analyst: '#f59e0b',
    Translator: '#8b5cf6',
    Reviewer: '#ef4444',
    TestRunner: '#84cc16',
    Vision: '#a855f7',
    Planner: '#f59e0b',
  };

  let nodes = [];
  let nodeCounter = 1;
  let agentNames = [];
  let selectedId = null;
  let linkSourceId = null;
  let dragState = null;
  let planSummary = '自定义计划：{task}';
  let validationTimer = null;

  const els = {};

  function init() {
    els.canvas = document.getElementById('dag-canvas');
    els.svg = document.getElementById('dag-svg');
    els.wrap = document.getElementById('dag-canvas-wrap');
    els.inspector = document.getElementById('compose-inspector');
    els.validation = document.getElementById('compose-validation');
    els.jsonPreview = document.getElementById('compose-json');
    els.palette = document.getElementById('agent-palette');
    els.planSummary = document.getElementById('compose-plan-summary');

    if (!els.canvas) return;

    els.canvas.addEventListener('mousedown', onCanvasMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    window.addEventListener('keydown', onKeyDown);

    if (els.planSummary) {
      els.planSummary.addEventListener('input', () => {
        planSummary = els.planSummary.value;
        syncJson();
      });
    }

    document.getElementById('btn-add-node')?.addEventListener('click', () => addNode());
    document.getElementById('btn-clear-canvas')?.addEventListener('click', clearCanvas);
    document.getElementById('btn-validate-plan')?.addEventListener('click', validatePlan);
    document.getElementById('btn-submit-plan')?.addEventListener('click', submitPlan);
    document.getElementById('btn-load-template')?.addEventListener('click', loadTemplate);
    document.getElementById('btn-save-template')?.addEventListener('click', saveTemplate);

    renderPalette();
    renderAll();
  }

  function setAgentNames(names) {
    agentNames = names.filter(n => n !== 'Planner');
    renderPalette();
  }

  function renderPalette() {
    if (!els.palette) return;
    const list = agentNames.length ? agentNames : ['Research', 'Writer', 'Analyst', 'Reviewer'];
    els.palette.innerHTML = list.map(name => {
      const color = AGENT_COLORS[name] || '#6366f1';
      return `<button type="button" class="palette-agent" data-agent="${name}" style="border-left-color:${color}">
        <span class="dot" style="background:${color}"></span>${name}
      </button>`;
    }).join('');
    els.palette.querySelectorAll('.palette-agent').forEach(btn => {
      btn.addEventListener('click', () => {
        const rect = els.wrap?.getBoundingClientRect();
        const x = rect ? Math.max(20, (rect.width / 2) - NODE_W / 2 + (Math.random() * 40 - 20)) : 80;
        const y = rect ? Math.max(20, (rect.height / 2) - NODE_H / 2 + (Math.random() * 40 - 20)) : 80;
        addNode({ agent: btn.dataset.agent, x, y });
      });
    });
  }

  function addNode(partial = {}) {
    const id = partial.id || uniqueId();
    const agent = partial.agent || agentNames[0] || 'Research';
    const node = {
      id,
      agent,
      task: partial.task || `${agent}：{task}`,
      depends_on: [...(partial.depends_on || [])],
      reason: partial.reason || '',
      x: partial.x ?? 40 + (nodes.length % 4) * (NODE_W + 24),
      y: partial.y ?? 40 + Math.floor(nodes.length / 4) * (NODE_H + 36),
    };
    nodes.push(node);
    selectedId = id;
    linkSourceId = null;
    renderAll();
    return node;
  }

  function uniqueId() {
    while (nodes.some(n => n.id === `n${nodeCounter}`)) nodeCounter += 1;
    return `n${nodeCounter++}`;
  }

  function removeNode(id) {
    nodes = nodes.filter(n => n.id !== id);
    nodes.forEach(n => {
      n.depends_on = n.depends_on.filter(d => d !== id);
    });
    if (selectedId === id) selectedId = nodes[0]?.id || null;
    if (linkSourceId === id) linkSourceId = null;
    renderAll();
  }

  function getNode(id) {
    return nodes.find(n => n.id === id);
  }

  function toggleDependency(fromId, toId) {
    if (fromId === toId) return false;
    const target = getNode(toId);
    if (!target) return false;
    const idx = target.depends_on.indexOf(fromId);
    if (idx >= 0) {
      target.depends_on.splice(idx, 1);
      return true;
    }
    if (wouldCycle(fromId, toId)) {
      setValidationMsg('不能创建循环依赖', 'error');
      return false;
    }
    target.depends_on.push(fromId);
    return true;
  }

  function wouldCycle(fromId, toId) {
    const visited = new Set();
    function reachable(start, goal) {
      if (start === goal) return true;
      if (visited.has(start)) return false;
      visited.add(start);
      const node = getNode(start);
      if (!node) return false;
      return node.depends_on.some(dep => reachable(dep, goal));
    }
    return reachable(fromId, toId);
  }

  function autoLayout() {
    const layers = topoLayers(nodes);
    const colW = NODE_W + 48;
    const rowH = NODE_H + 40;
    layers.forEach((layer, li) => {
      layer.forEach((node, ni) => {
        node.x = 40 + li * colW;
        node.y = 40 + ni * rowH;
      });
    });
    renderAll();
  }

  function clearCanvas() {
    if (nodes.length && !confirm('清空画布上所有节点？')) return;
    nodes = [];
    selectedId = null;
    linkSourceId = null;
    renderAll();
  }

  function buildPlan() {
    return {
      summary: planSummary || '自定义计划：{task}',
      steps: nodes.map(n => n.agent),
      assignments: nodes.map(n => ({
        id: n.id,
        agent: n.agent,
        task: n.task,
        depends_on: [...n.depends_on],
        reason: n.reason || '',
      })),
    };
  }

  function syncJson() {
    if (els.jsonPreview) {
      els.jsonPreview.textContent = JSON.stringify(buildPlan(), null, 2);
    }
    scheduleValidation();
  }

  function scheduleValidation() {
    clearTimeout(validationTimer);
    validationTimer = setTimeout(validatePlanSilent, 400);
  }

  function setValidationMsg(msg, type = 'info') {
    if (!els.validation) return;
    els.validation.className = `compose-validation ${type}`;
    els.validation.textContent = msg;
  }

  async function validatePlanSilent() {
    if (!nodes.length) {
      setValidationMsg('画布为空 — 从左侧点击 Agent 或载入模板开始', 'info');
      return;
    }
    const task = document.getElementById('task-input')?.value.trim() || 'demo';
    try {
      const res = await apiFetch('/templates/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, custom_plan: buildPlan() }),
      });
      const data = await res.json();
      if (data.valid) {
        const parallel = countParallelLayers();
        setValidationMsg(`计划有效 · ${data.assignment_count} 节点 · ${parallel}`, 'ok');
      } else {
        setValidationMsg((data.errors || ['无效计划']).join('; '), 'error');
      }
    } catch (e) {
      setValidationMsg('校验请求失败', 'error');
    }
  }

  function countParallelLayers() {
    const layers = topoLayers(nodes);
    const maxParallel = Math.max(...layers.map(l => l.length), 0);
    return maxParallel > 1 ? `最多 ${maxParallel} 路并行` : '线性/串行';
  }

  async function validatePlan() {
    await validatePlanSilent();
    const cls = els.validation?.className || '';
    if (cls.includes('ok')) alert('计划有效 ✓');
    else if (cls.includes('error')) alert(els.validation.textContent);
  }

  async function loadTemplate() {
    const id = document.getElementById('compose-template-select')?.value;
    if (!id) return alert('请先选择模板');
    const res = await apiFetch(`/templates/${id}`);
    const data = await res.json();
    if (data.error) return alert(data.error);
    const tpl = data.template;
    planSummary = tpl.summary || planSummary;
    if (els.planSummary) els.planSummary.value = planSummary;
    nodes = (tpl.assignments || []).map((a, i) => ({
      id: a.id,
      agent: a.agent,
      task: a.task,
      depends_on: a.depends_on || [],
      reason: a.reason || '',
      x: 40 + (i % 3) * (NODE_W + 40),
      y: 40 + Math.floor(i / 3) * (NODE_H + 36),
    }));
    nodeCounter = nodes.length + 1;
    autoLayout();
  }

  async function saveTemplate() {
    if (!nodes.length) return alert('画布上没有节点');
    await validatePlanSilent();
    if (els.validation?.classList.contains('error')) {
      return alert('计划无效，请先修正：' + els.validation.textContent);
    }
    const name = prompt('模板名称', planSummary.replace('{task}', '').trim() || '我的计划');
    if (!name) return;
    const custom_plan = buildPlan();
    const res = await apiFetch('/templates/saved', {
      method: 'POST',
      body: JSON.stringify({ name, description: '', custom_plan }),
    });
    if (res.ok) {
      if (typeof window.showToast === 'function') window.showToast('模板已保存', 'ok');
      if (typeof window.loadTemplates === 'function') window.loadTemplates();
    } else {
      alert('保存失败');
    }
  }

  async function submitPlan() {
    const task = document.getElementById('task-input')?.value.trim();
    if (!task) return alert('请先在上方输入任务描述（支持 {task} 占位符）');
    if (!nodes.length) return alert('画布上没有节点');
    await validatePlanSilent();
    if (els.validation?.classList.contains('error')) {
      return alert('计划无效，请先修正：' + els.validation.textContent);
    }
    const custom_plan = buildPlan();
    if (typeof window.switchView === 'function') window.switchView('run');
    if (typeof window.submitTask === 'function') {
      await window.submitTask({ custom_plan });
    }
  }

  function renderAll() {
    renderCanvas();
    renderInspector();
    syncJson();
  }

  function renderCanvas() {
    if (!els.canvas || !els.svg) return;
    els.canvas.querySelectorAll('.dag-node').forEach(el => el.remove());
    els.svg.innerHTML = '';

    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = '<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#818cf8"/></marker>';
    els.svg.appendChild(defs);

    const positions = {};
    nodes.forEach(node => {
      positions[node.id] = { x: node.x, y: node.y, node };
      const el = document.createElement('div');
      el.className = 'dag-node';
      if (node.id === selectedId) el.classList.add('selected');
      if (node.id === linkSourceId) el.classList.add('link-source');
      el.dataset.id = node.id;
      el.style.left = `${node.x}px`;
      el.style.top = `${node.y}px`;
      el.style.borderColor = AGENT_COLORS[node.agent] || '#6366f1';
      el.innerHTML = `
        <div class="port port-in" data-port="in" title="连入：上游完成后再执行"></div>
        <div class="node-body">
          <div class="agent-name">${escapeHtml(node.agent)}</div>
          <div class="node-id">${escapeHtml(node.id)}</div>
          <div class="dep-badge">${node.depends_on.length ? '↑' + node.depends_on.length : '起点'}</div>
        </div>
        <div class="port port-out" data-port="out" title="连出：拖到下游节点"></div>
      `;

      el.querySelector('.node-body').addEventListener('mousedown', e => startDrag(e, node.id));
      el.querySelector('.port-out').addEventListener('click', e => {
        e.stopPropagation();
        linkSourceId = linkSourceId === node.id ? null : node.id;
        renderCanvas();
        renderInspector();
      });
      el.querySelector('.port-in').addEventListener('click', e => {
        e.stopPropagation();
        if (linkSourceId && linkSourceId !== node.id) {
          toggleDependency(linkSourceId, node.id);
          linkSourceId = null;
          renderAll();
        } else {
          selectedId = node.id;
          renderAll();
        }
      });
      el.addEventListener('click', e => {
        if (e.target.classList.contains('port')) return;
        selectedId = node.id;
        renderAll();
      });

      els.canvas.appendChild(el);
    });

    const maxX = Math.max(...nodes.map(n => n.x + NODE_W), 400);
    const maxY = Math.max(...nodes.map(n => n.y + NODE_H), 320);
    els.canvas.style.width = `${maxX + 60}px`;
    els.canvas.style.height = `${maxY + 60}px`;

    nodes.forEach(n => {
      n.depends_on.forEach(depId => {
        const from = positions[depId];
        const to = positions[n.id];
        if (!from || !to) return;
        drawEdge(from.x + NODE_W, from.y + NODE_H / 2, to.x, to.y + NODE_H / 2, depId, n.id);
      });
    });

    if (linkSourceId) {
      setValidationMsg(`连线中：从 ${linkSourceId} 的输出端口点击目标节点的输入端口`, 'info');
    }
  }

  function drawEdge(x1, y1, x2, y2, fromId, toId) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const mx = (x1 + x2) / 2;
    const d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
    path.setAttribute('d', d);
    path.setAttribute('class', 'dag-edge');
    path.setAttribute('marker-end', 'url(#arrow)');
    path.dataset.from = fromId;
    path.dataset.to = toId;
    path.addEventListener('click', () => {
      if (confirm(`删除依赖 ${fromId} → ${toId}？`)) {
        const target = getNode(toId);
        if (target) {
          target.depends_on = target.depends_on.filter(d => d !== fromId);
          renderAll();
        }
      }
    });
    els.svg.appendChild(path);
  }

  function renderInspector() {
    if (!els.inspector) return;
    const node = selectedId ? getNode(selectedId) : null;
    if (!node) {
      els.inspector.innerHTML = `<div class="empty">点击画布节点编辑属性<br><br>
        <strong>操作提示</strong><ul class="hint-list">
          <li>左侧点击 Agent 添加到画布</li>
          <li>拖拽节点自由摆放</li>
          <li>点击右侧圆点 → 再点目标左侧圆点连线</li>
          <li>点击连线可删除依赖</li>
          <li>支持并行分叉与多路汇聚</li>
        </ul></div>`;
      return;
    }

    const agentOpts = (agentNames.length ? agentNames : ['Research', 'Writer', 'Reviewer']).map(a =>
      `<option value="${a}" ${a === node.agent ? 'selected' : ''}>${a}</option>`).join('');

    const depChecks = nodes.filter(n => n.id !== node.id).map(n => {
      const checked = node.depends_on.includes(n.id) ? 'checked' : '';
      return `<label class="dep-check"><input type="checkbox" data-dep="${n.id}" ${checked}>
        <span>${n.id}</span> · ${n.agent}</label>`;
    }).join('') || '<div class="empty" style="padding:0">无其他节点</div>';

    els.inspector.innerHTML = `
      <div class="inspector-section">
        <label>节点 ID<input id="insp-id" value="${escapeAttr(node.id)}"></label>
        <label>Agent<select id="insp-agent">${agentOpts}</select></label>
        <label>任务描述<textarea id="insp-task" rows="3">${escapeHtml(node.task)}</textarea>
          <span class="field-hint">可用 {task} 引用用户输入</span></label>
        <label>调度说明<input id="insp-reason" value="${escapeAttr(node.reason)}" placeholder="可选"></label>
      </div>
      <div class="inspector-section">
        <div class="section-label">上游依赖（全部完成后才执行）</div>
        <div id="insp-deps">${depChecks}</div>
      </div>
      <div class="inspector-actions">
        <button type="button" id="insp-dup">复制节点</button>
        <button type="button" id="insp-del" class="danger">删除</button>
      </div>
    `;

    document.getElementById('insp-id')?.addEventListener('change', e => {
      const val = e.target.value.trim();
      if (!val || nodes.some(n => n.id === val && n.id !== node.id)) {
        alert('ID 无效或重复');
        e.target.value = node.id;
        return;
      }
      const oldId = node.id;
      node.id = val;
      nodes.forEach(n => {
        n.depends_on = n.depends_on.map(d => (d === oldId ? val : d));
      });
      if (selectedId === oldId) selectedId = val;
      if (linkSourceId === oldId) linkSourceId = val;
      renderAll();
    });

    document.getElementById('insp-agent')?.addEventListener('change', e => {
      node.agent = e.target.value;
      renderAll();
    });

    document.getElementById('insp-task')?.addEventListener('input', e => {
      node.task = e.target.value;
      syncJson();
    });

    document.getElementById('insp-reason')?.addEventListener('input', e => {
      node.reason = e.target.value;
      syncJson();
    });

    els.inspector.querySelectorAll('#insp-deps input[type=checkbox]').forEach(cb => {
      cb.addEventListener('change', () => {
        const depId = cb.dataset.dep;
        if (cb.checked) {
          if (!wouldCycle(depId, node.id)) node.depends_on.push(depId);
          else { cb.checked = false; setValidationMsg('不能创建循环依赖', 'error'); }
        } else {
          node.depends_on = node.depends_on.filter(d => d !== depId);
        }
        renderAll();
      });
    });

    document.getElementById('insp-dup')?.addEventListener('click', () => {
      const copy = addNode({
        agent: node.agent,
        task: node.task,
        reason: node.reason,
        depends_on: [...node.depends_on],
        x: node.x + 24,
        y: node.y + 24,
      });
      selectedId = copy.id;
      renderAll();
    });

    document.getElementById('insp-del')?.addEventListener('click', () => removeNode(node.id));
  }

  function startDrag(e, id) {
    if (e.button !== 0) return;
    e.preventDefault();
    const node = getNode(id);
    if (!node) return;
    selectedId = id;
    dragState = {
      id,
      startX: e.clientX,
      startY: e.clientY,
      origX: node.x,
      origY: node.y,
    };
  }

  function onMouseMove(e) {
    if (!dragState) return;
    const node = getNode(dragState.id);
    if (!node) return;
    node.x = Math.max(0, dragState.origX + (e.clientX - dragState.startX));
    node.y = Math.max(0, dragState.origY + (e.clientY - dragState.startY));
    renderCanvas();
  }

  function onMouseUp() {
    dragState = null;
  }

  function onCanvasMouseDown(e) {
    if (e.target === els.canvas || e.target === els.wrap) {
      selectedId = null;
      linkSourceId = null;
      renderAll();
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Delete' || e.key === 'Backspace') {
      if (document.activeElement?.tagName === 'INPUT' || document.activeElement?.tagName === 'TEXTAREA') return;
      if (selectedId) removeNode(selectedId);
    }
    if (e.key === 'Escape') {
      linkSourceId = null;
      renderAll();
    }
  }

  function topoLayers(nodeList) {
    if (!nodeList.length) return [];
    const byId = Object.fromEntries(nodeList.map(n => [n.id, n]));
    const depth = {};
    function calc(id, seen = new Set()) {
      if (depth[id] !== undefined) return depth[id];
      if (seen.has(id)) return 0;
      seen.add(id);
      const deps = byId[id]?.depends_on || [];
      depth[id] = deps.length ? Math.max(...deps.map(d => calc(d, seen)) + 1) : 0;
      return depth[id];
    }
    nodeList.forEach(n => calc(n.id));
    const max = Math.max(...Object.values(depth), 0);
    const layers = Array.from({ length: max + 1 }, () => []);
    nodeList.forEach(n => layers[depth[n.id]].push(n));
    return layers;
  }

  function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  function escapeAttr(text) {
    return String(text).replace(/"/g, '&quot;');
  }

export const ComposeEditor = {
  init,
  setAgentNames,
  renderAll,
  buildPlan,
  loadFromTemplate: loadTemplate,
};
