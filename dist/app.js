import {buildSynthesis} from "./modules/synthesis-engine.js";

const state = {
  manifest: null,
  terms: null,
  word: null,
  entries: [],
  senses: [],
  supplement: {},
  gcide: [],
  morphology: [],
  wiktionary: {status: "idle", groups: []},
  synthesisContext: "",
  synthesisAi: null,
  view: "sense",
  selectedSense: null,
  selectedSynset: null,
  relationType: null,
  relationTargets: [],
  graphDepth: 5,
  graphTraversal: null,
  graphRequest: 0,
  cache: new Map(),
  suggestionIndex: -1,
};

const $ = (id) => document.getElementById(id);
const searchInput = $("word-search");
const suggestions = $("suggestions");
const posNames = { n: "noun", v: "verb", a: "adjective", s: "adjective satellite", r: "adverb" };
const GRAPH_NODES_PER_LEVEL = 20;
const GRAPH_TOTAL_NODE_LIMIT = 100;
const graphSvgs = () => [$("relation-graph"), $("relation-graph-expanded")].filter(Boolean);
const graphStatuses = () => [$("graph-status"), $("graph-dialog-status")].filter(Boolean);
const relationTabContainers = () => [$("relation-tabs"), $("graph-dialog-relation-tabs")].filter(Boolean);
const depthControls = () => [...document.querySelectorAll("[data-graph-depth]")];

function setGraphStatusText(text, truncated = false) {
  graphStatuses().forEach((status) => {
    status.textContent = text;
    status.classList.toggle("truncated", truncated);
  });
}

function clearGraphViews() {
  graphSvgs().forEach((svg) => { svg.innerHTML = ""; });
}

async function fetchJson(path) {
  if (state.cache.has(path)) return state.cache.get(path);
  const promise = fetch(path).then((response) => {
    if (!response.ok) throw new Error(`Could not load ${path}`);
    return response.json();
  });
  state.cache.set(path, promise);
  return promise;
}

async function fetchCompressedJson(path) {
  return fetchGzipJson(`${path}.gz`);
}

async function fetchGzipJson(path) {
  if (state.cache.has(path)) return state.cache.get(path);
  const promise = fetch(path).then(async (response) => {
    if (!response.ok) throw new Error(`Could not load ${path}`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    let text;
    if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      text = await new Response(stream).text();
    } else {
      text = new TextDecoder().decode(bytes);
    }
    return JSON.parse(text);
  });
  state.cache.set(path, promise);
  return promise;
}

async function wordShard(term) {
  const bytes = new TextEncoder().encode(term);
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return fetchCompressedJson(`./data/words/${hash.slice(0, 2)}.json`);
}

async function lexicalShard(term) {
  const bytes = new TextEncoder().encode(term);
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return fetchCompressedJson(`./data/lexical/${hash.slice(0, 2)}.json`);
}

async function loadSupplement(term) {
  const shard = await lexicalShard(term);
  return shard[term] || {};
}

async function dictionaryShard(source, term) {
  const bytes = new TextEncoder().encode(term);
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
  const prefix = hash.slice(0, 2);
  return source === "wiktionary"
    ? fetchGzipJson(`./data/${source}/${prefix}.json.gz`)
    : fetchCompressedJson(`./data/${source}/${prefix}.json`);
}

async function loadDictionary(source, term) {
  try {
    const shard = await dictionaryShard(source, term);
    return shard[term] || [];
  } catch (_) {
    return [];
  }
}

function synsetShard(id) {
  const match = id.match(/^oewn-(\d{2})/);
  return match ? match[1] : "other";
}

async function loadSynsets(ids) {
  const groups = new Map();
  ids.forEach((id) => {
    const shard = synsetShard(id);
    if (!groups.has(shard)) groups.set(shard, []);
    groups.get(shard).push(id);
  });
  const output = new Map();
  await Promise.all([...groups].map(async ([shard, shardIds]) => {
    const records = await fetchCompressedJson(`./data/synsets/${shard}.json`);
    shardIds.forEach((id) => { if (records[id]) output.set(id, records[id]); });
  }));
  return output;
}

function normalizeTerm(value) { return value.trim().toLocaleLowerCase().replace(/\s+/g, " "); }
function prettyRelation(value) { return value.replaceAll("_", " "); }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

function plainText(html) {
  const template = document.createElement("template");
  template.innerHTML = String(html || "");
  return (template.content.textContent || "").replace(/\s+/g, " ").trim();
}

function updateLocation(push = true) {
  if (!state.word) return;
  const params = new URLSearchParams({word: state.word, view: state.view});
  if (state.selectedSense?.synset) params.set("sense", state.selectedSense.synset);
  if (state.relationType) params.set("relation", state.relationType);
  params.set("depth", String(state.graphDepth));
  const method = push ? "pushState" : "replaceState";
  history[method]({term: state.word, sense: state.selectedSense?.synset, view: state.view, relation: state.relationType, depth: state.graphDepth}, "", `#${params}`);
}

function setView(view, updateUrl = true) {
  state.view = ["sense", "full", "synthesis"].includes(view) ? view : "sense";
  $("sense-view").hidden = state.view !== "sense";
  $("full-view").hidden = state.view !== "full";
  $("synthesis-view").hidden = state.view !== "synthesis";
  document.querySelectorAll(".view-switcher button").forEach((button) => {
    const active = button.dataset.view === state.view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active);
  });
  if (updateUrl) updateLocation();
}

async function openTerm(rawTerm, preferredSense = null, updateUrl = true) {
  const term = normalizeTerm(rawTerm);
  if (!term) return;
  closeSuggestions();
  searchInput.value = term;
  setLoading(term);
  try {
    const hasLocalWiktionary = state.manifest.supplements.wiktionary?.mode === "complete local extraction";
    const [shard, supplement, gcide, localWiktionary] = await Promise.all([
      wordShard(term), loadSupplement(term), loadDictionary("gcide", term),
      hasLocalWiktionary ? loadDictionary("wiktionary", term) : Promise.resolve([]),
    ]);
    const entries = shard[term] || [];
    const senseRefs = entries.flatMap((entry) => entry.senses.map((sense) => ({...sense, entry})));
    const synsets = await loadSynsets(senseRefs.map((sense) => sense.synset));
    state.word = term;
    state.entries = entries;
    state.senses = senseRefs.map((sense) => ({...sense, data: synsets.get(sense.synset)})).filter((sense) => sense.data);
    state.supplement = supplement;
    state.gcide = gcide;
    state.wiktionary = localWiktionary.length
      ? {status: "local", groups: localWiktionary}
      : {status: "loading", groups: []};
    state.morphology = await loadMorphology(supplement);
    if (state.senses.length) {
      renderWord();
      const selected = state.senses.find((sense) => sense.synset === preferredSense) || state.senses[0];
      await selectSense(selected, false);
    } else {
      state.selectedSense = null;
      state.selectedSynset = null;
      setNotFound(term);
    }
    renderDossier();
    renderSynthesis();
    if (!localWiktionary.length) fetchWiktionary(term);
    if (updateUrl) updateLocation();
  } catch (error) {
    setError(error.message);
  }
}

function setLoading(term) {
  state.synthesisContext = "";
  state.synthesisAi = null;
  $("current-word").textContent = term;
  $("word-stats").innerHTML = "";
  $("sense-list").innerHTML = '<div class="empty-state"><span class="loader"></span></div>';
  $("definition-panel").innerHTML = '<div class="empty-state"><span class="loader"></span><p>Finding every sense…</p></div>';
  relationTabContainers().forEach((container) => { container.innerHTML = ""; });
  clearGraphViews();
  $("relation-list").innerHTML = "";
  setGraphStatusText("Preparing graph…");
  $("dossier-word").textContent = term;
  $("coverage-stack").innerHTML = "";
  $("dossier").innerHTML = '<div class="empty-state"><span class="loader"></span><p>Gathering lexical records…</p></div>';
  $("synthesis-word").textContent = term;
  $("synthesis-status").innerHTML = "";
  $("synthesis-panel").innerHTML = '<div class="empty-state"><span class="loader"></span><p>Preparing the evidence synthesis…</p></div>';
}

function setNotFound(term) {
  $("current-word").textContent = term;
  $("sense-list").innerHTML = "";
  $("word-stats").innerHTML = '<span class="meta-pill">0 WordNet senses</span>';
  $("definition-panel").innerHTML = `<div class="error-card"><strong>No WordNet sense found.</strong><br>“${escapeHtml(term)}” is not listed as a word form in OEWN 2025. The Full word view may still contain records from other sources.</div>`;
  relationTabContainers().forEach((container) => { container.innerHTML = ""; });
  clearGraphViews();
  $("relation-list").innerHTML = "";
  $("relation-count").textContent = "0 links";
  setGraphStatusText("No relation graph");
  renderSynthesis();
}

function setError(message) {
  $("definition-panel").innerHTML = `<div class="error-card"><strong>The lexical data could not be opened.</strong><br>${escapeHtml(message)}</div>`;
  $("dossier").innerHTML = `<div class="error-card"><strong>The lexical data could not be opened.</strong><br>${escapeHtml(message)}</div>`;
  $("synthesis-panel").innerHTML = `<div class="error-card"><strong>The evidence synthesis could not be prepared.</strong><br>${escapeHtml(message)}</div>`;
}

function renderWord() {
  $("current-word").textContent = state.word;
  const parts = [...new Set(state.entries.map((entry) => entry.pos))];
  $("word-stats").innerHTML = `<span class="meta-pill">${state.senses.length} ${state.senses.length === 1 ? "sense" : "senses"}</span>` +
    parts.map((pos) => `<span class="pos-pill">${escapeHtml(posNames[pos] || pos)}</span>`).join("");
  $("sense-list").innerHTML = state.senses.map((sense, index) => `
    <button class="sense-item" data-sense="${escapeHtml(sense.synset)}" type="button">
      <span class="sense-number">${String(index + 1).padStart(2, "0")}</span>
      <span class="sense-copy"><strong>${escapeHtml(posNames[sense.data.pos] || sense.data.pos)}</strong><span>${escapeHtml(sense.data.definition || "No definition supplied")}</span></span>
    </button>`).join("");
  $("sense-list").scrollLeft = 0;
  $("sense-list").querySelectorAll(".sense-item").forEach((button) => button.addEventListener("click", () => {
    const sense = state.senses.find((item) => item.synset === button.dataset.sense);
    selectSense(sense);
  }));
}

async function selectSense(sense, updateUrl = true) {
  if (!sense) return;
  state.selectedSense = sense;
  state.selectedSynset = sense.data;
  const senseButtons = $("sense-list").querySelectorAll(".sense-item");
  senseButtons.forEach((button) => button.classList.toggle("active", button.dataset.sense === sense.synset));
  const activeButton = $("sense-list").querySelector(".sense-item.active");
  if (activeButton && matchMedia("(max-width: 720px)").matches) {
    $("sense-list").scrollLeft = Math.max(0, activeButton.offsetLeft - 16);
  }
  renderDefinition();
  renderRelationTabs();
  if (updateUrl) updateLocation();
  await selectRelation(state.relationType, false);
}

function renderDefinition() {
  const synset = state.selectedSynset;
  const examples = synset.examples.length ? `<p class="section-label">Examples</p><ul class="examples">${synset.examples.map((example) => `<li>${escapeHtml(example)}</li>`).join("")}</ul>` : "";
  $("definition-panel").innerHTML = `
    <div class="sense-topline"><span class="sense-id">${escapeHtml(synset.id)}</span><button class="copy-button" id="copy-id" type="button">Copy sense ID</button></div>
    <p class="definition">${escapeHtml(synset.definition || "No definition supplied.")}</p>
    <div class="lemmas">${synset.lemmas.map((lemma) => `<span class="lemma">${escapeHtml(lemma)}</span>`).join("")}</div>
    ${examples}
    <p class="evidence-note">This is one candidate sense from ${escapeHtml(state.manifest.release)}. The explorer does not decide whether it fits a sentence or authorizes an action.</p>`;
  $("copy-id").addEventListener("click", async (event) => {
    await navigator.clipboard.writeText(synset.id);
    event.currentTarget.textContent = "Copied";
    setTimeout(() => { event.currentTarget.textContent = "Copy sense ID"; }, 1200);
  });
}

function availableRelations() {
  const semantic = Object.keys(state.selectedSynset.relations).map((name) => ({name, kind: "semantic", count: state.selectedSynset.relations[name].length}));
  const lexical = Object.keys(state.selectedSense.relations || {}).map((name) => ({name, kind: "lexical", count: state.selectedSense.relations[name].length}));
  return [...semantic, ...lexical].sort((a, b) => a.name.localeCompare(b.name) || a.kind.localeCompare(b.kind));
}

function renderRelationTabs() {
  const relations = availableRelations();
  if (!relations.some((item) => `${item.kind}:${item.name}` === state.relationType)) {
    const first = relations.find((item) => item.name === "hyponym") || relations.find((item) => item.name === "hypernym") || relations[0];
    state.relationType = first ? `${first.kind}:${first.name}` : null;
  }
  const markup = relations.length ? relations.map((relation) => {
    const key = `${relation.kind}:${relation.name}`;
    return `<button class="${key === state.relationType ? "active" : ""}" data-relation="${escapeHtml(key)}" type="button">${escapeHtml(prettyRelation(relation.name))} · ${relation.count}</button>`;
  }).join("") : '<span class="meta-pill">No recorded relations</span>';
  relationTabContainers().forEach((container) => {
    container.innerHTML = markup;
    container.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => selectRelation(button.dataset.relation)));
  });
}

async function selectRelation(key, rerenderTabs = true) {
  state.relationType = key;
  if (rerenderTabs) {
    renderRelationTabs();
    updateLocation(false);
  }
  if (!key) {
    state.relationTargets = [];
    state.graphTraversal = null;
    renderDepthControl(null);
    return renderRelations();
  }
  const request = ++state.graphRequest;
  const [kind, name] = key.split(":");
  renderDepthControl(kind);
  setGraphStatusText("Tracing relation levels…");
  let targetIds;
  if (kind === "semantic") targetIds = state.selectedSynset.relations[name] || [];
  else targetIds = (state.selectedSense.relations[name] || []).map((item) => item.synset);
  const loaded = await loadSynsets(targetIds);
  if (request !== state.graphRequest) return;
  state.relationTargets = targetIds.map((id) => loaded.get(id)).filter(Boolean);
  state.graphTraversal = await buildRecursiveGraph(kind, name, state.graphDepth, request);
  if (request !== state.graphRequest) return;
  renderRelations();
}

function renderDepthControl(kind) {
  const recursive = kind === "semantic" || kind === "lexical";
  const effectiveDepth = recursive ? state.graphDepth : 1;
  depthControls().forEach((control) => {
    control.querySelectorAll("button").forEach((button) => {
      const depth = Number(button.dataset.depth);
      button.disabled = !recursive && depth > 1;
      button.setAttribute("aria-pressed", depth === effectiveDepth);
      button.title = `Trace ${depth} relation ${depth === 1 ? "level" : "levels"}`;
    });
  });
}

async function buildRecursiveGraph(kind, name, requestedDepth, request) {
  const effectiveDepth = requestedDepth;
  const root = state.selectedSynset;
  const rootKey = kind === "lexical" ? state.selectedSense.id : root.id;
  const rootNode = {data: root, depth: 0, key: rootKey, senseId: state.selectedSense.id};
  const nodes = [rootNode];
  const nodeById = new Map([[rootKey, rootNode]]);
  const edges = [];
  const edgeKeys = new Set();
  let frontier = [rootNode];
  let reachedDepth = 0;
  let truncated = false;

  for (let depth = 1; depth <= effectiveDepth && frontier.length; depth += 1) {
    const buckets = frontier.map((source) => {
      if (kind === "lexical") {
        const sense = depth === 1 && source.key === rootKey
          ? state.selectedSense
          : (source.data.senses || []).find((item) => item.id === source.senseId);
        const targets = (sense?.relations?.[name] || []).map((item) => ({
          synset: item.synset, sense: item.sense, key: item.sense || `${item.synset}:unknown`,
        }));
        return {source, targets};
      }
      const targets = (source.data.relations[name] || []).map((synset) => ({synset, sense: null, key: synset}));
      return {source, targets};
    }).filter((bucket) => bucket.targets.length);
    if (!buckets.length) break;

    const totalCandidates = buckets.reduce((sum, bucket) => sum + bucket.targets.length, 0);
    const selected = [];
    const longest = Math.max(...buckets.map((bucket) => bucket.targets.length));
    selection: for (let index = 0; index < longest; index += 1) {
      for (const bucket of buckets) {
        if (bucket.targets[index]) selected.push({source: bucket.source, target: bucket.targets[index]});
        if (selected.length >= GRAPH_NODES_PER_LEVEL) break selection;
      }
    }
    if (selected.length < totalCandidates) truncated = true;

    const loaded = await loadSynsets([...new Set(selected.map((item) => item.target.synset))]);
    if (request !== state.graphRequest) return null;
    const nextFrontier = [];
    let levelHadEdge = false;
    for (const item of selected) {
      const target = loaded.get(item.target.synset);
      if (!target) continue;
      levelHadEdge = true;
      if (!nodeById.has(item.target.key)) {
        if (nodes.length >= GRAPH_TOTAL_NODE_LIMIT + 1) {
          truncated = true;
          continue;
        }
        const node = {data: target, depth, key: item.target.key, senseId: item.target.sense};
        nodeById.set(item.target.key, node);
        nodes.push(node);
        nextFrontier.push(node);
      }
      const edgeKey = `${item.source.key}>${item.target.key}`;
      if (!edgeKeys.has(edgeKey)) {
        edgeKeys.add(edgeKey);
        edges.push({source: item.source.key, target: item.target.key, depth});
      }
    }
    if (levelHadEdge) reachedDepth = depth;
    frontier = nextFrontier;
  }

  return {nodes, edges, requestedDepth, effectiveDepth, reachedDepth, truncated, kind, rootKey};
}

function renderRelations() {
  const targets = state.relationTargets;
  $("relation-count").textContent = `${targets.length} ${targets.length === 1 ? "link" : "links"}`;
  renderGraph(state.graphTraversal);
  renderGraphStatus(state.graphTraversal);
  $("relation-list").innerHTML = targets.length ? targets.slice(0, 50).map((target) => `
    <button class="relation-link" type="button" data-target="${escapeHtml(target.id)}"><strong>${escapeHtml(target.lemmas[0] || target.id)}</strong><span>${escapeHtml(target.id)}</span></button>`).join("") : '<div class="empty-state"><p>No links in this relation.</p></div>';
  $("relation-list").querySelectorAll("[data-target]").forEach((button) => button.addEventListener("click", () => openRelated(button.dataset.target)));
}

function renderGraphStatus(traversal) {
  if (!traversal) {
    setGraphStatusText("No relation graph");
    return;
  }
  const relatedNodes = Math.max(0, traversal.nodes.length - 1);
  const depthText = traversal.reachedDepth === traversal.effectiveDepth
    ? `${traversal.effectiveDepth} ${traversal.effectiveDepth === 1 ? "level" : "levels"}`
    : `${traversal.reachedDepth} of ${traversal.effectiveDepth} levels reached`;
  const notes = [depthText, `${relatedNodes} ${relatedNodes === 1 ? "node" : "nodes"}`];
  if (traversal.kind === "lexical") notes.push("sense graph");
  if (traversal.truncated) notes.push("bounded view");
  setGraphStatusText(notes.join(" · "), traversal.truncated);
}

function renderGraph(traversal) {
  updateGraphDialogContext();
  graphSvgs().forEach((svg) => renderGraphSvg(svg, traversal));
}

function renderGraphSvg(svg, traversal) {
  const center = {x: 360, y: 260};
  if (!traversal) {
    svg.innerHTML = "";
    return;
  }
  const positions = new Map([[traversal.rootKey, center]]);
  const deepest = Math.max(1, traversal.reachedDepth);
  for (let depth = 1; depth <= deepest; depth += 1) {
    const levelNodes = traversal.nodes.filter((node) => node.depth === depth);
    const radiusX = 52 + (228 * depth / deepest);
    const radiusY = 38 + (152 * depth / deepest);
    const phase = depth % 2 ? -Math.PI / 2 : -Math.PI / 2 + Math.PI / Math.max(levelNodes.length, 1);
    levelNodes.forEach((node, index) => {
      const angle = phase + (Math.PI * 2 * index / Math.max(levelNodes.length, 1));
      positions.set(node.key, {x: center.x + Math.cos(angle) * radiusX, y: center.y + Math.sin(angle) * radiusY});
    });
  }
  const edgeMarkup = traversal.edges.map((edge) => {
    const source = positions.get(edge.source), target = positions.get(edge.target);
    return source && target ? `<line class="graph-edge" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}"/>` : "";
  }).join("");
  const nodeMarkup = traversal.nodes.filter((node) => node.depth > 0).map((node) => {
    const point = positions.get(node.key);
    if (!point) return "";
    const lemma = node.data.lemmas[0] || node.data.id;
    const labelLines = graphLabelLines(lemma, node.depth > 2 ? 12 : 18);
    const box = graphNodeBox(labelLines, node.depth);
    const labelMarkup = graphLabelMarkup(labelLines, point);
    const senseDetail = traversal.kind === "lexical" && node.senseId ? ` · ${node.senseId}` : "";
    return `<g class="graph-node" data-depth="${node.depth}" tabindex="0" role="button" aria-label="Open ${escapeHtml(lemma)}, depth ${node.depth}" data-target="${escapeHtml(node.data.id)}"><title>${escapeHtml(lemma)}${escapeHtml(senseDetail)} · depth ${node.depth}</title><rect x="${point.x - box.width / 2}" y="${point.y - box.height / 2}" width="${box.width}" height="${box.height}" rx="10"/><text>${labelMarkup}</text></g>`;
  }).join("");
  const centerLines = graphLabelLines(state.word, 18);
  const centerBox = graphNodeBox(centerLines, 0);
  svg.innerHTML = edgeMarkup + nodeMarkup +
    `<g class="graph-node graph-center"><rect x="${center.x - centerBox.width / 2}" y="${center.y - centerBox.height / 2}" width="${centerBox.width}" height="${centerBox.height}" rx="12"/><text>${graphLabelMarkup(centerLines, center)}</text></g>`;
  svg.querySelectorAll("[data-target]").forEach((node) => {
    node.addEventListener("click", () => openRelated(node.dataset.target));
    node.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") openRelated(node.dataset.target); });
  });
}

function shortLabel(value, limit = 14) { return value.length > limit ? `${value.slice(0, Math.max(1, limit - 1))}…` : value; }
function graphLabelLines(value, limit = 12) {
  const text = String(value || "").replaceAll("_", " ").trim();
  if (text.length <= limit) return [text];
  const separators = [...text.matchAll(/[\s-]/g)].map((match) => match.index);
  if (!separators.length) {
    const breakAt = Math.min(limit, Math.ceil(text.length / 2));
    return [text.slice(0, breakAt), shortLabel(text.slice(breakAt), limit + 1)].filter(Boolean);
  }
  const beforeLimit = separators.filter((index) => index > 1 && index <= limit).pop();
  const breakAt = beforeLimit ?? separators.find((index) => index > limit && index < limit * 2) ?? limit;
  const keepSeparator = text[breakAt] === "-" ? 1 : 0;
  const first = text.slice(0, breakAt + keepSeparator).trim();
  const second = text.slice(breakAt + 1).trim();
  return [shortLabel(first, limit + 1), shortLabel(second, limit + 1)].filter(Boolean);
}
function graphLabelMarkup(lines, point) {
  const lineHeight = 12;
  const firstY = point.y + 3 - ((lines.length - 1) * lineHeight / 2);
  return lines.map((line, index) => `<tspan x="${point.x}" y="${firstY + index * lineHeight}">${escapeHtml(line)}</tspan>`).join("");
}
function graphNodeBox(lines, depth) {
  const longestLine = Math.max(...lines.map((line) => line.length), 1);
  if (depth === 0) return {width: Math.max(124, Math.min(168, 30 + longestLine * 7.2)), height: lines.length > 1 ? 54 : 46};
  const maximumWidth = depth > 2 ? 90 : 124;
  return {
    width: Math.max(70, Math.min(maximumWidth, 24 + longestLine * 6.6)),
    height: lines.length > 1 ? 44 : 36,
  };
}
async function openRelated(id) {
  const records = await loadSynsets([id]);
  const target = records.get(id);
  if (target?.lemmas?.length) openTerm(target.lemmas[0], id);
}

async function loadMorphology(supplement) {
  const output = [];
  const seen = new Set();
  const addForms = (lemma, forms) => (forms || []).forEach(([form, features]) => {
    const key = `${lemma}\u0000${form}\u0000${features}`;
    if (seen.has(key)) return;
    seen.add(key);
    output.push({lemma, form, features});
  });
  addForms(state.word, supplement.f);
  const lemmas = [...new Set(supplement.l || [])].slice(0, 20);
  await Promise.all(lemmas.map(async (lemma) => {
    const record = await loadSupplement(normalizeTerm(lemma));
    addForms(lemma, record.f);
  }));
  return output.sort((a, b) => a.lemma.localeCompare(b.lemma) || a.form.localeCompare(b.form) || a.features.localeCompare(b.features));
}

async function fetchWiktionary(term) {
  const requested = term;
  try {
    const url = `https://en.wiktionary.org/api/rest_v1/page/definition/${encodeURIComponent(term)}`;
    const response = await fetch(url, {headers: {Accept: "application/json"}});
    if (!response.ok) throw new Error(`Wiktionary returned ${response.status}`);
    const payload = await response.json();
    if (state.word !== requested) return;
    const groups = (payload.en || []).map((group) => ({
      partOfSpeech: group.partOfSpeech || "Entry",
      definitions: (group.definitions || []).map((item) => ({
        definition: plainText(item.definition),
        example: plainText((item.parsedExamples || [])[0]?.example || (item.examples || [])[0]),
      })).filter((item) => item.definition),
    })).filter((group) => group.definitions.length);
    state.wiktionary = {status: groups.length ? "available" : "none", groups};
  } catch (error) {
    if (state.word !== requested) return;
    state.wiktionary = {status: "unavailable", groups: [], message: error.message};
  }
  renderDossier();
  renderSynthesis();
}

function featureLabel(feature) {
  const labels = {
    N: "noun", V: "verb", ADJ: "adjective", ADV: "adverb", SG: "singular", PL: "plural",
    PRS: "present", PST: "past", FUT: "future", INF: "infinitive", NFIN: "nonfinite",
    "V.PTCP": "participle", GER: "gerund", IND: "indicative", SBJV: "subjunctive", IMP: "imperative",
    "1": "first person", "2": "second person", "3": "third person", COMP: "comparative", SPRL: "superlative",
  };
  return labels[feature] || feature.toLocaleLowerCase().replaceAll(".", " ");
}

function stressSummary(phones) {
  const marks = (phones.match(/[012]/g) || []).join("–");
  const syllables = (phones.match(/[A-Z]+[012]/g) || []).length;
  return `${syllables} ${syllables === 1 ? "syllable" : "syllables"}${marks ? ` · stress ${marks}` : ""}`;
}

function coverageItem(label, available, detail, live = false) {
  const stateClass = live ? "live" : available ? "available" : "";
  return `<div class="coverage-item ${stateClass}"><i aria-hidden="true"></i><strong>${escapeHtml(label)}</strong><span>${escapeHtml(detail)}</span></div>`;
}

function renderDossier() {
  if (!state.word) return;
  const supplement = state.supplement || {};
  const pronunciations = supplement.p || [];
  const ipaPronunciations = supplement.i || [];
  const derivations = supplement.d || [];
  const parts = [...new Set([
    ...state.entries.map((entry) => posNames[entry.pos] || entry.pos),
    ...state.morphology.flatMap((row) => row.features.split(";").slice(0, 1).map(featureLabel)),
  ])];
  const wikiAvailable = ["available", "local"].includes(state.wiktionary.status);
  const gcideAvailable = state.gcide.length > 0;
  $("dossier-word").textContent = state.word;
  $("coverage-stack").innerHTML = [
    coverageItem("Open English WordNet", state.senses.length > 0, state.senses.length ? `${state.senses.length} senses` : "no record"),
    coverageItem("CMUdict", pronunciations.length > 0, pronunciations.length ? `${pronunciations.length} pronunciations` : "no record"),
    coverageItem("IPA dictionaries", ipaPronunciations.length > 0, ipaPronunciations.length ? `${ipaPronunciations.length} dialect records` : "no record"),
    coverageItem("UniMorph", state.morphology.length > 0 || derivations.length > 0, `${state.morphology.length} forms · ${derivations.length} links`),
    coverageItem("Wiktionary", wikiAvailable, state.wiktionary.status === "loading" ? "checking fallback" : state.wiktionary.status === "local" ? "local record" : wikiAvailable ? "live fallback" : state.wiktionary.status, state.wiktionary.status === "loading"),
    coverageItem("GCIDE", gcideAvailable, gcideAvailable ? `${state.gcide.length} historical records` : "no record"),
  ].join("");

  const wikiIpaCandidates = state.wiktionary.status === "local" ? state.wiktionary.groups.flatMap((entry) => (entry.pr || []).map((item) => [
    (item.tags || []).join(", ") || "Wiktionary", item.ipa || item.enpr, item.ipa ? "IPA" : "enPR",
  ])).filter((item) => item[1]) : [];
  const wikiIpaSeen = new Set();
  const wikiIpa = wikiIpaCandidates.filter((item) => {
    const key = item.join("\u0000");
    if (wikiIpaSeen.has(key)) return false;
    wikiIpaSeen.add(key);
    return true;
  });
  const pronunciationRows = [
    ...pronunciations.map((phones) => `<div class="pronunciation-row"><span class="arpabet">${escapeHtml(phones)}</span><div class="microcopy">${escapeHtml(stressSummary(phones))} · CMUdict · US English ARPAbet</div></div>`),
    ...ipaPronunciations.map(([dialect, value, license]) => `<div class="pronunciation-row"><span class="arpabet">${escapeHtml(value)}</span><div class="microcopy">${escapeHtml(dialect)} · Open Dict Data IPA · ${escapeHtml(license)}</div></div>`),
    ...wikiIpa.map(([dialect, value, system]) => `<div class="pronunciation-row"><span class="arpabet">${escapeHtml(value)}</span><div class="microcopy">${escapeHtml(dialect)} · Wiktionary ${escapeHtml(system)}</div></div>`),
  ];
  const pronunciationBody = pronunciationRows.length
    ? `<div class="pronunciation-list">${pronunciationRows.join("")}</div>`
    : '<p class="empty-record">No attached pronunciation record was found for this spelling.</p>';

  const visibleForms = state.morphology.slice(0, 120);
  const grammarBody = state.morphology.length
    ? `<div class="grammar-summary">${parts.map((part) => `<span class="feature-pill">${escapeHtml(part)}</span>`).join("")}</div><div class="table-wrap"><table class="forms-table"><thead><tr><th>Lemma</th><th>Form</th><th>Grammar features</th></tr></thead><tbody>${visibleForms.map((row) => `<tr><td>${escapeHtml(row.lemma)}</td><td>${escapeHtml(row.form)}</td><td>${row.features.split(";").map(featureLabel).map(escapeHtml).join(" · ")}</td></tr>`).join("")}</tbody></table></div>${state.morphology.length > visibleForms.length ? `<p class="microcopy">Showing ${visibleForms.length} of ${state.morphology.length} attached forms.</p>` : ""}`
    : `<div class="grammar-summary">${parts.map((part) => `<span class="feature-pill">${escapeHtml(part)}</span>`).join("")}</div><p class="empty-record">${parts.length ? "Parts of speech above come from WordNet. No UniMorph paradigm is attached." : "No grammar record is attached for this spelling."}</p>`;

  const derivationBody = derivations.length
    ? `<div class="derivation-list">${derivations.slice(0, 100).map(([direction, related, posChange, affix]) => `<div class="derivation-row"><strong><span class="direction">${direction === "out" ? "derived →" : "source ←"}</span> ${escapeHtml(related)}</strong><span>${escapeHtml(posChange.replace(":", " → "))} · affix ${escapeHtml(affix || "not supplied")}</span></div>`).join("")}</div>${derivations.length > 100 ? `<p class="microcopy">Showing 100 of ${derivations.length} links.</p>` : ""}`
    : '<p class="empty-record">No UniMorph derivational link is attached for this spelling.</p>';

  const oewnDefinitions = state.senses.map((sense) => ({pos: posNames[sense.data.pos] || sense.data.pos, definition: sense.data.definition, example: sense.data.examples[0]}));
  const oewnGroup = oewnDefinitions.length ? `<div class="definition-group"><h3>Open English WordNet · ${oewnDefinitions.length} candidate senses</h3><div class="definition-list">${oewnDefinitions.map((item) => `<div class="definition-row">${escapeHtml(item.definition || "No definition supplied.")}${item.example ? `<small>${escapeHtml(item.example)}</small>` : ""}</div>`).join("")}</div></div>` : "";
  let wikiGroup = '<p class="empty-record">Checking the English Wiktionary fallback endpoint…</p>';
  let etymologyBody = '<p class="empty-record">No local etymology record was found for this spelling.</p>';
  if (state.wiktionary.status === "local") {
    wikiGroup = state.wiktionary.groups.map((entry) => {
      const definitions = (entry.s || []).flatMap((sense) => (sense.glosses || []).map((definition) => ({definition, example: (sense.examples || [])[0]?.text})));
      return `<div class="definition-group"><h3>Wiktionary · ${escapeHtml(entry.p || "entry")}</h3><div class="definition-list">${definitions.slice(0, 60).map((item) => `<div class="definition-row">${escapeHtml(item.definition)}${item.example ? `<small>${escapeHtml(item.example)}</small>` : ""}</div>`).join("")}</div></div>`;
    }).join("");
    const etymologies = [...new Set(state.wiktionary.groups.map((entry) => entry.e).filter(Boolean))];
    if (etymologies.length) etymologyBody = etymologies.map((value) => `<div class="definition-row">${escapeHtml(value)}</div>`).join("");
  } else if (state.wiktionary.status === "available") {
    wikiGroup = state.wiktionary.groups.map((group) => `<div class="definition-group"><h3>Wiktionary · ${escapeHtml(group.partOfSpeech)}</h3><div class="definition-list">${group.definitions.slice(0, 30).map((item) => `<div class="definition-row">${escapeHtml(item.definition)}${item.example ? `<small>${escapeHtml(item.example)}</small>` : ""}</div>`).join("")}</div></div>`).join("");
  } else if (state.wiktionary.status === "none") {
    wikiGroup = '<p class="empty-record">The Wiktionary endpoint returned no English definition.</p>';
  } else if (state.wiktionary.status === "unavailable") {
    wikiGroup = '<p class="empty-record">The live Wiktionary record is unavailable. Attached local sources remain usable.</p>';
  }
  const gcideGroup = gcideAvailable ? `<div class="definition-group"><h3>GCIDE · historical supplemental records</h3><div class="definition-list">${state.gcide.flatMap((entry) => (entry.d || []).map((definition) => ({definition, pos: (entry.p || []).join(" · ")}))).slice(0, 60).map((item) => `<div class="definition-row">${escapeHtml(item.definition)}${item.pos ? `<small>${escapeHtml(item.pos)}</small>` : ""}</div>`).join("")}</div></div>` : "";

  const wordUrl = `https://en.wiktionary.org/wiki/${encodeURIComponent(state.word.replaceAll(" ", "_"))}`;
  const sources = [
    [state.manifest.label, "definitions, senses, semantic and lexical relations", state.manifest.license, state.manifest.source_url],
    [state.manifest.supplements.cmudict.label, state.manifest.supplements.cmudict.scope, state.manifest.supplements.cmudict.license, state.manifest.supplements.cmudict.source_url],
    [state.manifest.supplements.unimorph.label, state.manifest.supplements.unimorph.scope, state.manifest.supplements.unimorph.license, state.manifest.supplements.unimorph.source_url],
    [state.manifest.supplements.ipa_dict.label, state.manifest.supplements.ipa_dict.scope, state.manifest.supplements.ipa_dict.license, state.manifest.supplements.ipa_dict.source_url],
    [state.manifest.supplements.wiktionary.label, state.manifest.supplements.wiktionary.scope, state.manifest.supplements.wiktionary.license, state.manifest.supplements.wiktionary.source_url],
    ...(state.manifest.supplements.gcide ? [[state.manifest.supplements.gcide.label, state.manifest.supplements.gcide.authority, state.manifest.supplements.gcide.license, state.manifest.supplements.gcide.source_url]] : []),
  ];
  $("dossier").innerHTML = `
    <div class="dossier-header"><div><p class="eyebrow">All attached evidence</p><h1>${escapeHtml(state.word)}</h1><p>Matching spellings are gathered without collapsing their senses or hiding source disagreements.</p></div><a class="source-link" href="${wordUrl}" target="_blank" rel="noopener noreferrer">Open full Wiktionary entry ↗</a></div>
    <div class="dossier-grid">
      <article class="info-card"><div class="info-card-head"><h2>Pronunciation</h2><span class="source-badge">CMUdict + IPA + Wiktionary</span></div>${pronunciationBody}</article>
      <article class="info-card"><div class="info-card-head"><h2>Grammar &amp; forms</h2><span class="source-badge">UniMorph + OEWN</span></div>${grammarBody}</article>
      <article class="info-card"><div class="info-card-head"><h2>Word formation</h2><span class="source-badge">UniMorph</span></div>${derivationBody}</article>
      <article class="info-card"><div class="info-card-head"><h2>Etymology</h2><span class="source-badge">Wiktionary</span></div>${etymologyBody}</article>
      <article class="info-card"><div class="info-card-head"><h2>Definitions by source</h2><span class="source-badge">visible collisions</span></div>${oewnGroup}${wikiGroup}${gcideGroup}</article>
      <article class="info-card wide"><div class="info-card-head"><h2>Source ledger</h2><span class="source-badge">provenance</span></div><div class="source-ledger">${sources.map(([label, scope, license, url]) => `<div class="source-ledger-row"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(scope)} · ${escapeHtml(license)}</span><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Source ↗</a></div>`).join("")}</div></article>
    </div>`;
}

function currentSynthesis() {
  return buildSynthesis({
    term: state.word,
    senses: state.senses,
    wiktionary: state.wiktionary,
    gcide: state.gcide,
    context: state.synthesisContext,
    posNames,
  });
}

function renderSynthesis() {
  if (!state.word) return;
  const synthesis = currentSynthesis();
  const {candidates, ranked, best, cues, sourceCount, context, contextLine, proposal} = synthesis;
  $("synthesis-word").textContent = state.word;
  $("synthesis-status").innerHTML = [
    `<div class="synthesis-status-row"><strong>Evidence rows</strong><span>${candidates.length}</span></div>`,
    `<div class="synthesis-status-row"><strong>Sources</strong><span>${sourceCount}</span></div>`,
    `<div class="synthesis-status-row"><strong>Mode</strong><span>heuristic</span></div>`,
  ].join("");
  if (!ranked.length) {
    $("synthesis-panel").innerHTML = '<div class="error-card"><strong>No definitions are attached for this spelling.</strong><br>The synthesis pane preserves that absence instead of inventing a meaning.</div>';
    return;
  }
  const rows = ranked.slice(0, 8).map((candidate, index) => `<div class="candidate-row"><span class="candidate-rank">${String(index + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(candidate.source)} · ${escapeHtml(candidate.pos)}</strong><p>${escapeHtml(candidate.definition)}</p>${candidate.example ? `<small>Example: ${escapeHtml(candidate.example)}</small>` : ""}<small>Evidence ${escapeHtml(candidate.ref)} · agreement ${candidate.agreement}${candidate.contextMatch ? ` · context match ${candidate.contextMatch}` : ""}</small></div><span class="candidate-score">${candidate.score} pts</span></div>`).join("");
  const aiText = state.synthesisAi
    ? `<div class="ai-output">${escapeHtml(state.synthesisAi)}</div>`
    : '<div class="ai-output" id="synthesis-ai-output">No optional AI provider is configured. The deterministic heuristic draft remains available.</div>';
  $("synthesis-panel").innerHTML = `
    <div class="synthesis-header"><div><p class="eyebrow">Heuristic synthesis</p><h1>${escapeHtml(state.word)}</h1><p>Evidence is ranked for inspection. Colliding meanings remain visible, and this draft does not select a sense for execution.</p></div></div>
    <div class="synthesis-controls">
      <label for="synthesis-context">Optional context</label>
      <textarea id="synthesis-context" placeholder="Add a sentence or short context to rerank candidates…">${escapeHtml(state.synthesisContext)}</textarea>
      <div class="synthesis-actions"><button id="synthesis-run" type="button">Rerank candidates</button><button id="synthesis-ai" class="ai-button" type="button">Optional AI refinement</button><span class="synthesis-notice" id="synthesis-ai-note">AI is used only through an explicitly configured provider hook.</span></div>
    </div>
    <div class="synthesis-grid">
      <article class="synthesis-card"><h2>Candidate interpretation</h2><p>${escapeHtml(contextLine)}</p><div class="proposal">${escapeHtml(proposal)}</div><p class="synthesis-boundary">Generated proposal only. Source definitions, authority, and command execution stay separate.</p></article>
      <article class="synthesis-card"><h2>Shared lexical cues</h2><p>Repeated content words among the highest-ranked records.</p><div class="cue-list">${cues.length ? cues.map((cue) => `<span class="cue">${escapeHtml(cue)}</span>`).join("") : '<span class="empty-record">No repeated cue crossed the threshold.</span>'}</div></article>
      <article class="synthesis-card wide"><h2>Ranked evidence</h2><p>WordNet receives the highest lexical weight, followed by Wiktionary and GCIDE. Agreement and optional context affect ordering; they do not merge records.</p><div class="ranked-candidates">${rows}</div></article>
      <article class="synthesis-card wide"><h2>Optional AI refinement</h2><p>The UI can accept a separately configured AI provider, but the result remains labeled generated text and never replaces the evidence ledger.</p>${aiText}</article>
    </div>`;
  $("synthesis-context").addEventListener("input", (event) => { state.synthesisContext = event.target.value; });
  $("synthesis-run").addEventListener("click", () => renderSynthesis());
  $("synthesis-ai").addEventListener("click", refineWithOptionalAI);
}

async function refineWithOptionalAI() {
  const output = $("synthesis-ai-output");
  const button = $("synthesis-ai");
  const provider = window.lexiconAtlasAI;
  if (typeof provider !== "function") {
    if (output) output.textContent = "No optional AI provider is configured. Nothing was sent outside this page.";
    return;
  }
  button.disabled = true;
  if (output) output.textContent = "Generating an optional draft…";
  try {
    const result = await provider({term: state.word, context: state.synthesisContext, candidates: currentSynthesis().candidates.slice(0, 12)});
    state.synthesisAi = typeof result === "string" ? result : result?.text || JSON.stringify(result);
    renderSynthesis();
  } catch (error) {
    if (output) output.textContent = `Optional AI refinement failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function showSuggestions(query) {
  if (!state.terms || query.length < 2) return closeSuggestions();
  const exact = normalizeTerm(query);
  const matches = [];
  let low = 0, high = state.terms.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (state.terms[middle] < exact) low = middle + 1;
    else high = middle;
  }
  for (let index = low; index < state.terms.length && matches.length < 9; index += 1) {
    if (!state.terms[index].startsWith(exact)) break;
    matches.push(state.terms[index]);
  }
  if (!matches.length) return closeSuggestions();
  state.suggestionIndex = -1;
  suggestions.innerHTML = matches.map((term) => `<button type="button" role="option" data-term="${escapeHtml(term)}">${escapeHtml(term)}</button>`).join("");
  suggestions.hidden = false;
  suggestions.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => openTerm(button.dataset.term)));
}
function closeSuggestions() { suggestions.hidden = true; suggestions.innerHTML = ""; state.suggestionIndex = -1; }
function moveSuggestion(direction) {
  const items = [...suggestions.querySelectorAll("button")];
  if (!items.length) return;
  state.suggestionIndex = (state.suggestionIndex + direction + items.length) % items.length;
  items.forEach((item, index) => item.setAttribute("aria-selected", index === state.suggestionIndex));
  items[state.suggestionIndex].scrollIntoView({block: "nearest"});
}

function parseHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  const depth = Number(params.get("depth") || 5);
  return {
    word: params.get("word") || "code",
    sense: params.get("sense"),
    view: params.get("view") || "sense",
    relation: params.get("relation") || "semantic:hyponym",
    depth: Number.isInteger(depth) && depth >= 1 && depth <= 5 ? depth : 5,
  };
}

function applyGraphLocation(target) {
  state.graphDepth = target.depth;
  state.relationType = /^(semantic|lexical):[a-z0-9_-]+$/i.test(target.relation || "") ? target.relation : "semantic:hyponym";
}

function updateGraphDialogContext() {
  const relationName = state.relationType ? prettyRelation(state.relationType.split(":")[1]) : "No relation selected";
  const senseId = state.selectedSense?.id ? ` · ${state.selectedSense.id}` : "";
  $("graph-dialog-title").textContent = `${state.word || "Word"} relation neighborhood`;
  $("graph-dialog-context").textContent = `${relationName}${senseId}`;
}

function openGraphDialog() {
  updateGraphDialogContext();
  renderRelationTabs();
  renderDepthControl(state.relationType?.split(":")[0] || null);
  renderGraphStatus(state.graphTraversal);
  renderGraph(state.graphTraversal);
  $("graph-expand").setAttribute("aria-pressed", "true");
  $("graph-dialog").showModal();
}

function closeGraphDialog() {
  if ($("graph-dialog").open) $("graph-dialog").close();
}

async function initialize() {
  try {
    [state.manifest, state.terms] = await Promise.all([fetchJson("./data/manifest.json"), fetchCompressedJson("./data/terms.json")]);
    $("dataset-status").textContent = `${state.manifest.label} + open dictionary sources · ${state.manifest.terms.toLocaleString()} indexed spellings`;
    $("about-metrics").innerHTML = [
      [state.manifest.counts.senses, "WordNet senses"], [state.manifest.supplements.ipa_dict.records, "IPA records"], [state.manifest.supplements.unimorph.forms, "inflected forms"]
    ].map(([value, label]) => `<div><strong>${Number(value).toLocaleString()}</strong><span>${label}</span></div>`).join("");
    const initial = parseHash();
    applyGraphLocation(initial);
    setView(initial.view, false);
    await openTerm(initial.word, initial.sense, false);
    updateLocation(false);
  } catch (error) {
    const detail = `${error.message}. This code-only checkout intentionally omits lexical datasets; see DATA_INSTALLATION.md and place generated assets under dist/data.`;
    $("dataset-status").textContent = "Lexical data is not installed";
    setError(detail);
  }
}

$("search-form").addEventListener("submit", (event) => { event.preventDefault(); openTerm(searchInput.value); });
searchInput.addEventListener("input", () => showSuggestions(searchInput.value));
searchInput.addEventListener("keydown", (event) => {
  if (suggestions.hidden) return;
  if (event.key === "ArrowDown") { event.preventDefault(); moveSuggestion(1); }
  if (event.key === "ArrowUp") { event.preventDefault(); moveSuggestion(-1); }
  if (event.key === "Escape") closeSuggestions();
  if (event.key === "Enter" && state.suggestionIndex >= 0) {
    event.preventDefault();
    openTerm(suggestions.querySelectorAll("button")[state.suggestionIndex].dataset.term);
  }
});
document.addEventListener("click", (event) => { if (!event.target.closest(".search")) closeSuggestions(); });
window.addEventListener("popstate", () => { const target = parseHash(); applyGraphLocation(target); setView(target.view, false); openTerm(target.word, target.sense, false); });
document.querySelectorAll(".view-switcher button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
$("about-button").addEventListener("click", () => $("about-dialog").showModal());
$("about-close").addEventListener("click", () => $("about-dialog").close());
depthControls().forEach((control) => control.querySelectorAll("button").forEach((button) => button.addEventListener("click", async () => {
  const depth = Number(button.dataset.depth);
  if (!Number.isInteger(depth) || depth < 1 || depth > 5 || button.disabled) return;
  state.graphDepth = depth;
  renderDepthControl(state.relationType?.split(":")[0] || null);
  updateLocation(false);
  await selectRelation(state.relationType, false);
})));
$("graph-expand").addEventListener("click", openGraphDialog);
$("graph-dialog-close").addEventListener("click", closeGraphDialog);
$("graph-dialog").addEventListener("click", (event) => { if (event.target === $("graph-dialog")) closeGraphDialog(); });
$("graph-dialog").addEventListener("close", () => $("graph-expand").setAttribute("aria-pressed", "false"));

initialize();
