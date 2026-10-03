const $ = id => document.getElementById(id);
const state = {transport: 'mcp', host: null, hostContext: {}, papers: [], total: 0, query: '', collection: '',
  libraryEntry: document.documentElement.dataset.view === 'library',
  document: null, pdf: null, page: 1, zoom: null, generation: 0, searchGeneration: 0,
  pages: [], selection: null, sending: false, loading: false, layoutRevision: 0, renderQueue: Promise.resolve()};
const pending = new Map();
const themeVariables = new Set();
const readerStyleProperties = {
  '--paper-reader-background-image': 'background-image',
  '--paper-reader-background-size': 'background-size',
  '--paper-reader-background-opacity': 'opacity',
  '--paper-reader-background-filter': 'filter',
  '--paper-reader-canvas-background': 'color',
  '--paper-reader-panel-background': 'color',
  '--paper-reader-glass-blur': 'backdrop-filter',
  '--paper-reader-paper-opacity': 'opacity',
};
let nextId = 0;
let pageObserver;
let resizeTimer;
let searchTimer;
let scrollFrame;

function rpc(method, params, timeout = 45000) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('阅读面板与聊天连接超时，请重新打开面板。')); }, timeout);
    pending.set(id, {resolve, reject, timer});
    window.parent.postMessage({jsonrpc: '2.0', id, method, params}, '*');
  });
}
function notify(method, params) { window.parent.postMessage({jsonrpc: '2.0', method, params}, '*'); }
function updatePaperPalette() {
  const style = getComputedStyle(document.documentElement);
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
  const painter = canvas.getContext('2d'); if (!painter) return;
  const rgb = value => {
    painter.clearRect(0, 0, 1, 1); painter.fillStyle = value; painter.fillRect(0, 0, 1, 1);
    return [...painter.getImageData(0, 0, 1, 1).data].slice(0, 3);
  };
  const bodyStyle = getComputedStyle(document.body);
  const background = rgb(bodyStyle.backgroundColor);
  const foreground = rgb(bodyStyle.color);
  if (!background || !foreground) return;
  for (const [index, channel] of ['r', 'g', 'b'].entries()) {
    $(`paper-${channel}`).setAttribute('tableValues', `${foreground[index] / 255} ${background[index] / 255}`);
  }
  const alpha = Number(style.getPropertyValue('--paper-reader-paper-opacity').trim() || 1);
  const opacity = Number.isFinite(alpha) ? Math.max(0, Math.min(1, alpha)) : 1;
  // Remove the paper fill while keeping dark source text opaque over the backdrop.
  $('paper-opacity').setAttribute('values', `1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  ${[.2126, .7152, .0722].map(weight => -weight * (1 - opacity)).join(' ')} 1 0`);
}
function applyHostTheme(context = {}) {
  const root = document.documentElement;
  state.hostContext = {...state.hostContext, ...context,
    styles: {...state.hostContext.styles, ...context.styles}};
  const skin = window.__CODEX_SKIN_THEME__?.enabled ? window.__CODEX_SKIN_THEME__ : null;
  const theme = skin?.theme || state.hostContext.theme || window.openai?.theme || (matchMedia('(prefers-color-scheme:light)').matches ? 'light' : 'dark');
  root.dataset.theme = theme === 'light' ? 'light' : 'dark';
  root.style.colorScheme = root.dataset.theme;
  const variables = {...window.openai?.styles?.variables, ...state.hostContext.styles?.variables, ...skin?.styles?.variables};
  const next = new Set();
  for (const [name, value] of Object.entries(variables)) {
    const property = name.startsWith('--color-') ? 'color' : readerStyleProperties[name];
    if (property && typeof value === 'string' && CSS.supports(property, value)) {
      next.add(name);
      if (root.style.getPropertyValue(name) !== value) root.style.setProperty(name, value);
    }
  }
  for (const name of themeVariables) if (!next.has(name)) root.style.removeProperty(name);
  themeVariables.clear(); for (const name of next) themeVariables.add(name);
  if (state.paperTheme === 'host') root.dataset.paperTheme = root.dataset.theme;
  updatePaperPalette();
}
function setPaperTheme(theme) {
  state.paperTheme = theme === 'original' || theme === 'light' ? 'original' : 'host';
  const followsHost = state.paperTheme === 'host';
  document.documentElement.dataset.paperMode = state.paperTheme;
  document.documentElement.dataset.paperTheme = followsHost ? document.documentElement.dataset.theme || 'dark' : 'light';
  $('paper-theme').textContent = followsHost ? '跟随 Codex' : '原色纸张';
  $('paper-theme').setAttribute('aria-pressed', String(followsHost));
  $('paper-theme').title = followsHost ? '切换原色纸张，核对图表原始颜色' : '恢复跟随 Codex 主题';
  try { localStorage.setItem('paper-reader:paper-theme', state.paperTheme); } catch { /* Sandboxed hosts may disable storage. */ }
  updatePaperPalette();
}
async function requestSidePanel() {
  try {
    if (window.openai?.requestDisplayMode) await window.openai.requestDisplayMode({mode: 'fullscreen'});
    else await rpc('ui/request-display-mode', {mode: 'fullscreen'}, 5000);
  } catch { /* The thread entrypoint still opens beside chat on hosts without mode requests. */ }
}
function notice(message = '', error = false) { $('notice').textContent = message; $('notice').hidden = !message; $('notice').classList.toggle('error', error); }
function unwrap(value) { return value?.result ?? value?.mcp_tool_result ?? value?.call_tool_result ?? value; }
async function callTool(name, args = {}) {
  let value;
  if (state.transport === 'http') {
    const response = await fetch('/api/tool', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, arguments: args})});
    if (!response.ok) throw new Error('本地阅读服务无法响应，请刷新页面重试。');
    value = await response.json();
  } else if (window.openai?.callTool) value = await window.openai.callTool(name, args);
  else value = await rpc('tools/call', {name, arguments: args});
  value = unwrap(value);
  if (value?.isError) throw new Error(value.content?.filter(part => part.type === 'text').map(part => part.text).join('\n') || '读取失败。');
  return value;
}
window.addEventListener('message', event => {
  if (event.source !== window.parent) return;
  let message = event.data;
  if (typeof message === 'string') { try { message = JSON.parse(message); } catch { return; } }
  if (!message || message.jsonrpc !== '2.0') return;
  if (pending.has(message.id)) {
    const entry = pending.get(message.id); pending.delete(message.id); clearTimeout(entry.timer);
    message.error ? entry.reject(new Error(message.error.message)) : entry.resolve(message.result);
  }
  if (message.method === 'ui/notifications/tool-result') consume(message.params);
  if (message.method === 'ui/notifications/host-context-changed') applyHostTheme(message.params);
});

function consume(raw) {
  const value = unwrap(raw)?.structuredContent ?? raw;
  if (value?.document && value.document.document_id !== state.document?.document_id) openDocument(value.document).catch(error => notice(error.message, true));
  if (typeof value?.query === 'string' && value.query && value.query !== state.query) { $('search').value = value.query; searchPapers(); }
}
function metadata(paper) { return [paper.authors?.slice(0, 2).join(', '), paper.year].filter(Boolean).join(' · '); }
function renderLibrary() {
  const fragment = document.createDocumentFragment();
  for (const paper of state.papers) {
    const button = document.createElement('button'); button.className = 'paper-card'; button.dataset.key = paper.item_key;
    button.classList.toggle('active', paper.item_key === state.document?.paper.item_key);
    const title = document.createElement('strong'); title.textContent = paper.title;
    const meta = document.createElement('span'); meta.textContent = metadata(paper) || 'Zotero 文献';
    button.append(title, meta); button.addEventListener('click', () => openPaper(paper.item_key)); fragment.append(button);
  }
  $('paper-list').replaceChildren(fragment);
  if (!state.papers.length) { const empty = document.createElement('div'); empty.className = 'list-placeholder'; empty.textContent = '没有找到论文，试试作者或标题中的关键词。'; $('paper-list').append(empty); }
  $('paper-count').textContent = `${state.total} 篇文献`;
  $('more').hidden = state.papers.length >= state.total;
}
async function searchPapers(append = false) {
  const generation = ++state.searchGeneration;
  state.query = $('search').value.trim(); state.collection = $('collection').value;
  const start = append ? state.papers.length : 0;
  $('more').disabled = true;
  try {
    const args = {query: state.query, start, limit: 40}; if (state.collection) args.collection_key = state.collection;
    const result = (await callTool('search_papers', args)).structuredContent;
    if (generation !== state.searchGeneration) return;
    state.papers = append ? [...state.papers, ...result.papers] : result.papers; state.total = result.total;
    renderLibrary(); notice();
  } catch (error) {
    if (generation !== state.searchGeneration) return;
    notice(error.message, true);
    if (!append) { $('paper-list').replaceChildren(); const empty = document.createElement('div'); empty.className = 'list-placeholder'; empty.textContent = '暂时无法读取文献库。也可以打开本地 PDF。'; $('paper-list').append(empty); }
  } finally { if (generation === state.searchGeneration) $('more').disabled = false; }
}
async function collections() {
  try {
    const values = (await callTool('list_paper_collections')).structuredContent.collections;
    const old = $('collection').value;
    $('collection').replaceChildren(new Option('全部文献', ''));
    for (const value of values) $('collection').add(new Option(value.name, value.key));
    $('collection').value = old;
  } catch (error) { notice(error.message, true); }
}
async function openPaper(key) {
  if (state.loading) return;
  state.loading = true; notice('正在打开论文原文…');
  try {
    const value = (await callTool('open_paper', {item_key: key})).structuredContent.document;
    await openDocument(value);
  } catch (error) { notice(error.message, true); }
  finally { state.loading = false; }
}
function base64Bytes(text) { const binary = atob(text); const bytes = new Uint8Array(binary.length); for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index); return bytes; }
async function pdfBytes(doc, generation) {
  if (state.transport === 'http') {
    const response = await fetch(`/pdf/${encodeURIComponent(doc.document_id)}`);
    if (!response.ok) throw new Error('PDF 文件读取失败。');
    return new Uint8Array(await response.arrayBuffer());
  }
  const bytes = new Uint8Array(doc.size);
  for (let offset = 0; offset < doc.size;) {
    if (generation !== state.generation) return null;
    const value = await callTool('read_pdf_chunk', {document_id: doc.document_id, offset, length: doc.chunk_bytes});
    const chunk = value._meta?.reader_data;
    if (!chunk || chunk.offset !== offset || chunk.bytes <= 0) throw new Error('PDF 数据不完整，请重新打开论文。');
    const decoded = base64Bytes(chunk.data);
    if (decoded.length !== chunk.bytes || offset + decoded.length > bytes.length) throw new Error('PDF 数据长度无效。');
    bytes.set(decoded, offset); offset += decoded.length;
    $('reader-status').textContent = `读取原文 ${Math.round(offset / doc.size * 100)}%`;
  }
  return bytes;
}
async function openDocument(doc, suppliedBytes = null) {
  const generation = ++state.generation;
  closeSelection(); state.document = doc; state.page = 1; state.zoom = null;
  pageObserver?.disconnect();
  for (const item of state.pages) { item.task?.cancel(); item.textLayer?.cancel(); }
  state.pages = []; $('pdf-pages').replaceChildren(); $('welcome').hidden = true;
  if (state.pdf) { const old = state.pdf; state.pdf = null; await old.destroy(); }
  if (generation !== state.generation) return;
  $('document-title').textContent = doc.paper.title; $('document-meta').textContent = metadata(doc.paper) || '原始 PDF';
  $('reader-status').textContent = '正在读取 PDF…'; setControls(false); renderLibrary();
  $('app').classList.add('library-hidden');
  const bytes = suppliedBytes || await pdfBytes(doc, generation);
  if (generation !== state.generation || !bytes) return;
  let passwordAttempts = 0;
  const task = globalThis.pdfjsLib.getDocument({data: bytes, isEvalSupported: false, useSystemFonts: true});
  task.onPassword = update => {
    passwordAttempts++;
    const password = window.prompt(passwordAttempts === 1 ? '这个 PDF 已加密，请输入密码：' : '密码不正确，请重新输入：');
    if (password === null) { task.destroy(); notice('已取消打开加密 PDF。'); } else update(password);
  };
  const pdf = await task.promise;
  if (generation !== state.generation) { await pdf.destroy(); return; }
  state.pdf = pdf; state.document.pages = pdf.numPages;
  await layoutPages(generation); setControls(true); notice();
  $('reader-status').textContent = `原始 PDF · ${pdf.numPages} 页`;
  await context();
}
function setControls(enabled) {
  for (const name of ['page-number', 'previous', 'next', 'fit', 'zoom-in', 'zoom-out', 'ask-page']) $(name).disabled = !enabled;
  $('page-total').textContent = `/ ${state.pdf?.numPages ?? '—'}`;
  $('page-number').max = state.pdf?.numPages || 1;
  updatePage(state.page);
}
function updatePage(page) {
  state.page = page; $('page-number').value = page;
  $('previous').disabled = !state.pdf || page <= 1; $('next').disabled = !state.pdf || page >= state.pdf.numPages;
}
async function layoutPages(generation = state.generation, anchor = 1) {
  const revision = ++state.layoutRevision;
  pageObserver?.disconnect();
  for (const item of state.pages) { item.task?.cancel(); item.textLayer?.cancel(); }
  state.pages = []; state.renderQueue = Promise.resolve(); $('pdf-pages').replaceChildren();
  const pdf = state.pdf;
  const width = Math.max(180, $('pdf-scroll').clientWidth - (matchMedia('(max-width:720px)').matches ? 24 : 40));
  for (let page = 1; page <= pdf.numPages; page++) {
    const value = await pdf.getPage(page);
    if (generation !== state.generation || pdf !== state.pdf || revision !== state.layoutRevision) return;
    const original = value.getViewport({scale: 1});
    const scale = state.zoom || width / original.width;
    const viewport = value.getViewport({scale});
    const element = document.createElement('div'); element.className = 'pdf-page'; element.dataset.page = page;
    element.style.width = `${viewport.width}px`; element.style.height = `${viewport.height}px`;
    element.style.setProperty('--scale-factor', scale); element.style.setProperty('--total-scale-factor', scale);
    const placeholder = document.createElement('div'); placeholder.className = 'page-placeholder'; placeholder.textContent = `第 ${page} 页`;
    element.append(placeholder); $('pdf-pages').append(element);
    state.pages.push({page, value, viewport, element, rendered: false, pending: false, generation});
  }
  $('fit').textContent = state.zoom ? `${Math.round(state.zoom * 100)}%` : '适合宽度';
  pageObserver = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) enqueuePage(state.pages[Number(entry.target.dataset.page) - 1]);
  }, {root: $('pdf-scroll'), rootMargin: '700px 0px'});
  state.pages.forEach(item => pageObserver.observe(item.element));
  goPage(anchor);
  await enqueuePage(state.pages[anchor - 1]);
}
function enqueuePage(item) {
  if (!item || item.rendered) return Promise.resolve();
  if (item.pending) return item.promise;
  item.pending = true;
  item.promise = state.renderQueue = state.renderQueue.catch(() => {}).then(() => renderPage(item));
  return item.promise;
}
async function renderPage(item) {
  if (!item || item.rendered || item.generation !== state.generation || !item.element.isConnected) return;
  item.pending = true;
  try {
    const canvas = document.createElement('canvas'); const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.ceil(item.viewport.width * ratio); canvas.height = Math.ceil(item.viewport.height * ratio);
    item.element.append(canvas);
    item.task = item.value.render({canvasContext: canvas.getContext('2d'), viewport: item.viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0]});
    await item.task.promise;
    if (item.generation !== state.generation || !item.element.isConnected) return;
    const text = document.createElement('div'); text.className = 'textLayer'; item.element.append(text);
    item.textLayer = new globalThis.pdfjsLib.TextLayer({textContentSource: await item.value.getTextContent(), container: text, viewport: item.viewport});
    await item.textLayer.render();
    item.element.querySelector('.page-placeholder')?.remove(); item.rendered = true;
  } catch (error) {
    if (error.name !== 'RenderingCancelledException' && item.generation === state.generation && item.element.isConnected) notice(`第 ${item.page} 页显示失败：${error.message}`, true);
  } finally { item.pending = false; }
}
function goPage(page) {
  if (!state.pdf) return;
  page = Math.max(1, Math.min(state.pdf.numPages, Number(page) || 1));
  const element = state.pages[page - 1]?.element;
  if (element) { $('pdf-scroll').scrollTop = element.offsetTop - $('pdf-pages').offsetTop + 12; enqueuePage(state.pages[page - 1]); }
  updatePage(page); context();
}
async function zoom(direction) {
  if (!state.pdf) return;
  const current = state.zoom || state.pages[0].viewport.scale;
  state.zoom = direction === 0 ? null : Math.max(.35, Math.min(2.5, current + direction * .15));
  closeSelection(); await layoutPages(state.generation, state.page);
}
function pageOf(node) { const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement; return Number(element?.closest('.pdf-page')?.dataset.page); }
function captureSelection() {
  if (!state.pdf) return;
  const selection = window.getSelection(); if (!selection?.rangeCount || selection.isCollapsed) return;
  const range = selection.getRangeAt(0);
  if (!$('pdf-pages').contains(range.startContainer) || !$('pdf-pages').contains(range.endContainer)) return;
  const text = selection.toString().trim(); if (!text) return;
  if (text.length > 8000) { notice('一次选段最多 8000 字，请缩小选区。', true); return; }
  const start = pageOf(range.startContainer); const end = pageOf(range.endContainer);
  if (!start || !end) return;
  state.selection = {text, page_start: Math.min(start, end), page_end: Math.max(start, end), document: structuredClone(state.document)};
  showSelection(); context();
}
function showSelection() {
  const selection = state.selection;
  $('selected-text').textContent = selection.text || '以这一页的原文、公式和图表为上下文提问。';
  $('selection-location').textContent = selection.page_start === selection.page_end ? `原文 · PDF 第 ${selection.page_start} 页` : `原文 · PDF 第 ${selection.page_start}–${selection.page_end} 页`;
  $('selection-summary').textContent = selection.text ? `已选中 ${selection.text.length} 字 · 查看原文` : '整页提问 · 查看说明';
  $('selection-excerpt').open = false;
  $('selection-panel').hidden = false;
  $('selection-status').textContent = state.transport === 'http' ? '复制引用或快捷问题，在左侧 Codex 粘贴后继续聊。' : '在左侧 Codex 继续提问，或使用快捷操作。';
}
function closeSelection() { state.selection = null; $('selection-panel').hidden = true; $('selection-status').textContent = ''; context(); }
function askPage() {
  state.selection = {text: '', page_start: state.page, page_end: state.page, document: structuredClone(state.document)};
  showSelection(); context();
}
function readingContext() {
  const doc = state.selection?.document || state.document;
  if (!doc) return null;
  return {title: doc.paper.title, item_key: doc.paper.item_key, attachment_key: doc.attachment_key,
    document_id: doc.document_id, page_start: state.selection?.page_start || state.page,
    page_end: state.selection?.page_end || state.page, selected_text: state.selection?.text || '',
    file_uri: doc.file_uri, zotero_uri: doc.zotero_uri};
}
async function context() {
  if (state.transport === 'http' || !state.document) return;
  const value = readingContext();
  try { await rpc('ui/update-model-context', {content: [{type: 'text', text: JSON.stringify({paper_reader: value})}]}, 5000); }
  catch { /* Sending a question includes the same context on hosts without this capability. */ }
}
async function sendQuestion(action) {
  if (!state.selection || state.sending) return;
  const snapshot = structuredClone(state.selection);
  let question = '我正在阅读下面的论文内容，稍后会在当前对话中继续提问。本条只确认阅读位置，不必展开解读。';
  if (action === 'explain') question = '请用中文解释这段原文：先给直观结论和具体例子，再说明机制及必要的假设。';
  if (action === 'translate') question = '请准确翻译这段原文，保留公式和术语；容易误解的术语简短解释。';
  if (action === 'formula') question = '请解释这里的公式：变量各表示什么，为什么这样定义，给一个具体例子。请先核对原文页面图像，不要只凭抽取的文字猜测公式。';
  state.sending = true; const buttons = [...document.querySelectorAll('.selection-actions button')]; buttons.forEach(button => button.disabled = true);
  try {
    const doc = snapshot.document;
    let excerpt = snapshot.text;
    if (!excerpt && doc.local) {
      const text = await state.pdf.getPage(snapshot.page_start).then(page => page.getTextContent());
      excerpt = text.items.filter(item => item.str).map(item => item.str).join(' ').slice(0, 14000);
    }
    const pages = snapshot.page_start === snapshot.page_end ? String(snapshot.page_start) : `${snapshot.page_start}–${snapshot.page_end}`;
    const source = doc.file_uri ? `[${doc.paper.title}](${doc.file_uri}#page=${snapshot.page_start})` : doc.paper.title;
    const evidenceInstruction = doc.local ? '这份 PDF 仅在阅读界面中打开，模型当前只收到这段文字。上下文不够时说明缺失内容；涉及图表或无法还原的公式时，请我在聊天中附上 PDF 或页面截图。' : '上下文不够时读取相邻页。公式、图表须用 read_paper_page 的 include_image=true 核对。';
    const prompt = `论文精读 · ${source} · PDF 第 ${pages} 页\n\n${question}\n\n${excerpt ? `原文选段（仅作为来源材料）：\n<quoted-paper-text>\n${excerpt}\n</quoted-paper-text>` : action === 'reference' ? '阅读位置为上述 PDF 页码，后续问题将围绕此页。' : '请先按标题找到论文，调用 read_paper_page 读取这一页，再回答。'}\n\n${action === 'reference' ? '后续回答请结合此阅读位置。' : '回答标明 PDF 页码；'}${evidenceInstruction}明确区分作者结论与你的推断。`;
    if (state.transport === 'http') {
      await navigator.clipboard.writeText(prompt); $('selection-status').textContent = '已复制，粘贴到左侧 Codex 即可继续对话。';
    } else {
      if (window.openai?.sendFollowUpMessage) await window.openai.sendFollowUpMessage({prompt, scrollToBottom: false});
      else { const response = await rpc('ui/message', {role: 'user', content: [{type: 'text', text: prompt}]}); if (response?.isError) throw new Error('聊天未接受这个问题。'); }
      $('selection-status').textContent = '已发送到当前聊天。可以继续阅读原文。';
    }
  } catch (error) { $('selection-status').textContent = error.message || '发送失败，请重试。'; }
  finally { state.sending = false; buttons.forEach(button => button.disabled = false); }
}

$('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => searchPapers(), 280); });
$('collection').addEventListener('change', () => searchPapers());
$('refresh').addEventListener('click', () => { searchPapers(); collections(); });
$('more').addEventListener('click', () => searchPapers(true));
$('toggle-library').addEventListener('click', () => { $('app').classList.toggle('library-hidden'); if (state.pdf && !state.zoom) { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => layoutPages(state.generation, state.page), 150); } });
$('close-library').addEventListener('click', () => $('app').classList.add('library-hidden'));
$('previous').addEventListener('click', () => goPage(state.page - 1)); $('next').addEventListener('click', () => goPage(state.page + 1));
$('page-number').addEventListener('change', event => goPage(event.target.value));
$('page-number').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); goPage(event.target.value); } });
$('zoom-in').addEventListener('click', () => zoom(1)); $('zoom-out').addEventListener('click', () => zoom(-1)); $('fit').addEventListener('click', () => zoom(0));
$('ask-page').addEventListener('click', askPage); $('close-selection').addEventListener('click', closeSelection);
document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => sendQuestion(button.dataset.action)));
$('selection-panel').addEventListener('mousedown', event => { if (event.target.closest('button')) event.preventDefault(); });
$('paper-theme').addEventListener('click', () => setPaperTheme(state.paperTheme === 'host' ? 'original' : 'host'));
$('pdf-scroll').addEventListener('mouseup', () => setTimeout(captureSelection, 15)); $('pdf-scroll').addEventListener('keyup', captureSelection);
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeSelection(); });
$('pdf-scroll').addEventListener('scroll', () => {
  if (!state.pdf || scrollFrame) return;
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = null;
    const top = $('pdf-scroll').getBoundingClientRect().top + 80;
    const active = state.pages.reduce((best, item) => Math.abs(item.element.getBoundingClientRect().top - top) < Math.abs(best.element.getBoundingClientRect().top - top) ? item : best, state.pages[0]);
    if (active && active.page !== state.page) { updatePage(active.page); context(); }
    for (const item of state.pages) {
      const selected = state.selection && item.page >= state.selection.page_start && item.page <= state.selection.page_end;
      if (item.rendered && !item.pending && !selected && Math.abs(item.page - state.page) > 5) {
        const canvas = item.element.querySelector('canvas'); if (canvas) { canvas.width = 0; canvas.height = 0; }
        item.textLayer?.cancel(); item.element.replaceChildren();
        const placeholder = document.createElement('div'); placeholder.className = 'page-placeholder'; placeholder.textContent = `第 ${item.page} 页`;
        item.element.append(placeholder); item.rendered = false;
      }
    }
  });
}, {passive: true});
window.addEventListener('resize', () => { if (state.pdf && !state.zoom) { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => layoutPages(state.generation, state.page), 200); } });
$('local-file').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 150 * 1024 * 1024) throw new Error('本版本支持最大 150 MB 的 PDF。');
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (!new TextDecoder().decode(bytes.slice(0, 1024)).includes('%PDF-')) throw new Error('请选择有效的 PDF 文件。');
    await openDocument({local: true, document_id: `local-${crypto.randomUUID()}`, paper: {title: file.name, authors: []}, size: file.size}, bytes);
  } catch (error) { notice(error.message, true); }
  finally { event.target.value = ''; }
});
$('side-panel').addEventListener('click', requestSidePanel);

async function boot() {
  applyHostTheme();
  let paperTheme = 'host';
  try { paperTheme = localStorage.getItem('paper-reader:paper-theme') || 'host'; } catch { /* Follow the host when storage is unavailable. */ }
  setPaperTheme(paperTheme);
  $('app').classList.remove('library-hidden');
  if (state.libraryEntry) {
    $('welcome').querySelector('h2').textContent = '选一篇论文，直接读原文';
    $('welcome').querySelector('p').textContent = '点击左侧论文即可打开 PDF。要在已有对话旁阅读，回到该对话，点右上角「＋」并选择「论文阅读器」。';
  }
  if (window.parent === window && location.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(location.hostname)) {
    state.transport = 'http'; $('transport-label').textContent = '选段后复制到左侧 Codex'; $('send-question').textContent = '复制选段到聊天 ↗';
  } else {
    if (!window.openai?.callTool) {
      try { state.host = await rpc('ui/initialize', {appInfo: {name: 'paper-reader', version: '0.2.6'}, appCapabilities: {}, protocolVersion: '2026-01-26'}); applyHostTheme(state.host?.hostContext); notify('ui/notifications/initialized', {}); }
      catch (error) { notice(error.message, true); return; }
    }
    $('side-panel').hidden = state.libraryEntry;
    if (window.openai?.toolOutput) consume(window.openai.toolOutput);
    if (!state.libraryEntry) requestSidePanel();
  }
  const params = new URLSearchParams(location.search);
  if (state.transport === 'http' && params.get('query')) $('search').value = params.get('query');
  await Promise.allSettled([searchPapers(), collections()]);
  if (state.transport === 'http' && params.get('item')) await openPaper(params.get('item'));
}
window.addEventListener('openai:set_globals', () => { applyHostTheme(); if (window.openai?.toolOutput) consume(window.openai.toolOutput); });
window.addEventListener('codex:theme-changed', event => {
  if (event.detail && typeof event.detail === 'object') window.__CODEX_SKIN_THEME__ = event.detail;
  applyHostTheme();
});
matchMedia('(prefers-color-scheme:light)').addEventListener('change', () => { if (state.transport === 'http') applyHostTheme(); });
new MutationObserver(() => {
  if (state.paperTheme === 'host') document.documentElement.dataset.paperTheme = document.documentElement.dataset.theme || 'dark';
  updatePaperPalette();
}).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'style']});
boot();
