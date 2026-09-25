const { Console } = require('node:console');
const { createInterface } = require('node:readline');
const { Writable } = require('node:stream');
const { inspect } = require('node:util');
const playwright = require('playwright');

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

const ACTIONABLE_ROLES = new Set([
  'button', 'checkbox', 'combobox', 'link', 'menuitem', 'menuitemcheckbox',
  'menuitemradio', 'option', 'radio', 'searchbox', 'slider', 'spinbutton',
  'switch', 'tab', 'textbox', 'treeitem',
]);
const SKIPPED_ROLES = new Set(['InlineTextBox', 'LineBreak', 'ListMarker', 'none', 'presentation']);
const STATE_NAMES = new Set([
  'checked', 'disabled', 'expanded', 'focused', 'hasPopup', 'level',
  'pressed', 'required', 'selected', 'url',
]);
const STRUCTURAL_ROLES = new Set([
  'generic', 'group', 'paragraph', 'list', 'listitem', 'separator', 'presentation', 'none',
]);
const PROTECTED_ROLES = new Set(['alert', 'dialog', 'form', 'heading', 'main', 'navigation']);
const FOOTER_ESSENTIAL_ROLES = new Set(['alert', 'dialog', 'form']);
// ponytail: cap individual text nodes at 500 code points; total observation budgets are separate.
const MAX_STATIC_TEXT_LENGTH = 500;

function pruneAccessibilityTree(tree) {
  const nodes = new Map((tree.nodes ?? []).map(node => [node.nodeId, node]));
  const ancestors = new Set();
  let references = 0;

  function visit(nodeId, parentName) {
    const node = nodes.get(nodeId);
    if (!node || ancestors.has(nodeId)) return [];
    const role = String(node.role?.value ?? '');
    const name = String(node.name?.value ?? '').trim();
    const state = Object.fromEntries((node.properties ?? [])
      .filter(property => STATE_NAMES.has(property.name) && property.value?.value != null)
      .map(property => [property.name, property.value.value]));
    if (node.value?.value != null) state.value = node.value.value;
    const skip = node.ignored || SKIPPED_ROLES.has(role)
      || (role === 'generic' && !name && !Object.keys(state).length)
      || (role === 'StaticText' && name && parentName.includes(name));
    ancestors.add(nodeId);
    const children = (node.childIds ?? []).flatMap(childId => visit(childId, name || parentName));
    ancestors.delete(nodeId);
    if (skip) return children;
    const result = { role };
    if (name) result.name = name;
    if (ACTIONABLE_ROLES.has(role.toLowerCase())) result.id = `e${++references}`;
    if (Object.keys(state).length) result.state = state;
    if (children.length) result.children = children;
    return [result];
  }

  return { nodes: [...nodes.values()]
    .filter(node => !Object.hasOwn(node, 'parentId'))
    .flatMap(node => visit(node.nodeId, '')) };
}

function capText(text) {
  const characters = Array.from(text);
  return characters.length <= MAX_STATIC_TEXT_LENGTH
    ? text : characters.slice(0, MAX_STATIC_TEXT_LENGTH - 1).join('').trimEnd() + '…';
}

function mergeAdjacentText(nodes) {
  const merged = [];
  for (const node of nodes) {
    const previous = merged.at(-1);
    if (node.role === 'StaticText' && previous?.role === 'StaticText'
      && !Object.keys(node.state ?? {}).length && !Object.keys(previous.state ?? {}).length) {
      previous.name = capText(`${previous.name} ${node.name}`.trim());
    } else {
      merged.push(node);
    }
  }
  return merged;
}

function interactiveDescendants(nodes) {
  return mergeAdjacentText(nodes.flatMap(node => ACTIONABLE_ROLES.has(node.role.toLowerCase())
    ? [node] : interactiveDescendants(node.children ?? [])));
}

function footerEssentials(nodes) {
  return nodes.flatMap(node => FOOTER_ESSENTIAL_ROLES.has(node.role.toLowerCase())
    ? [node] : footerEssentials(node.children ?? []));
}

function hasUniqueSemantics(node) {
  return Boolean(node.name) || Object.keys(node.state ?? {}).some(key => key !== 'level');
}

function fingerprint(node) {
  function structure(item) {
    return [item.role, item.name ?? null, Object.entries(item.state ?? {}).sort(),
      (item.children ?? []).map(structure)];
  }
  return JSON.stringify(structure(node));
}

function simplifyAccessibilityTree(tree, previousNavigation) {
  function simplify(node, parentName, parentIsInteractive) {
    const role = node.role;
    const roleKey = role.toLowerCase();
    const name = (node.name ?? '').trim();
    if (roleKey === 'image' && !(name && parentIsInteractive)) return [];
    if (role === 'StaticText') {
      // ponytail: lowercase misses case-fold expansions like ß/ss; add full folding if needed.
      if (!name || (parentName && parentName.toLowerCase().includes(name.toLowerCase()))) return [];
      return [{ role, name: capText(name) }];
    }
    const interactive = ACTIONABLE_ROLES.has(roleKey);
    const children = mergeAdjacentText((node.children ?? [])
      .flatMap(child => simplify(child, name || parentName, interactive)));
    if (roleKey === 'banner') {
      const controls = interactiveDescendants(children);
      return controls.length ? [{ role: 'navigation', children: controls }] : [];
    }
    if (roleKey === 'contentinfo') return footerEssentials(children);
    if (STRUCTURAL_ROLES.has(roleKey) && !hasUniqueSemantics(node)) return children;
    const result = { role };
    if (name) result.name = name;
    if (Object.hasOwn(node, 'id')) result.id = node.id;
    if (Object.keys(node.state ?? {}).length) result.state = node.state;
    if (children.length) result.children = children;
    if (!PROTECTED_ROLES.has(roleKey) && !interactive
      && !hasUniqueSemantics(result) && children.length === 1) return children;
    return [result];
  }

  const simplified = mergeAdjacentText(tree.nodes.flatMap(node => simplify(node, '', false)));
  const navigation = new Set();
  function collectNavigation(nodes) {
    for (const node of nodes) {
      if (node.role.toLowerCase() === 'navigation') navigation.add(fingerprint(node));
      collectNavigation(node.children ?? []);
    }
  }
  collectNavigation(simplified);

  function discardSeenNavigation(nodes) {
    return nodes.flatMap(node => {
      if (node.role.toLowerCase() === 'navigation' && previousNavigation.has(fingerprint(node))) return [];
      if (node.children?.length) node.children = discardSeenNavigation(node.children);
      return [node];
    });
  }
  return { tree: { nodes: discardSeenNavigation(simplified) }, navigation };
}

// Runs in the page: geometry the accessibility tree lacks (canvases, shadow-DOM controls, overlays).
// ponytail: scans every element and canvas pixel per observation; sample if huge pages get slow.
function collectPageGeometry() {
  const width = innerWidth;
  const height = innerHeight;
  const elements = [];
  (function walk(root) {
    for (const element of root.querySelectorAll('*')) {
      elements.push(element);
      if (element.shadowRoot) walk(element.shadowRoot);
    }
  })(document);
  const box = element => {
    const rect = element.getBoundingClientRect();
    return {
      x: Math.round(rect.x), y: Math.round(rect.y),
      width: Math.round(rect.width), height: Math.round(rect.height),
    };
  };
  const visible = element => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0
      && rect.top < height && rect.left < width && getComputedStyle(element).visibility !== 'hidden';
  };
  function ink(canvas) {
    // Copy instead of calling getContext on the page canvas, which could claim its context type.
    try {
      const copy = document.createElement('canvas');
      copy.width = canvas.width;
      copy.height = canvas.height;
      const context = copy.getContext('2d', { willReadFrequently: true });
      context.drawImage(canvas, 0, 0);
      const data = context.getImageData(0, 0, copy.width, copy.height).data;
      let pixels = 0, left = copy.width, top = copy.height, right = -1, bottom = -1;
      for (let index = 0; index < data.length; index += 4) {
        if (data[index] === data[0] && data[index + 1] === data[1]
          && data[index + 2] === data[2] && data[index + 3] === data[3]) continue;
        const x = (index / 4) % copy.width;
        const y = Math.floor(index / 4 / copy.width);
        pixels += 1;
        left = Math.min(left, x); top = Math.min(top, y);
        right = Math.max(right, x); bottom = Math.max(bottom, y);
      }
      return pixels ? { pixels, bbox: [left, top, right, bottom] } : { pixels };
    } catch {
      return undefined;
    }
  }

  const surfaces = elements
    .filter(element => ['canvas', 'svg'].includes(element.localName) && visible(element))
    .filter(element => element.getBoundingClientRect().width >= 100
      && element.getBoundingClientRect().height >= 100)
    .slice(0, 5)
    .map(element => element.localName === 'canvas'
      ? { tag: 'canvas', ...box(element), buffer: [element.width, element.height], ink: ink(element) }
      : { tag: 'svg', ...box(element) });
  const titledControls = [...new Set(elements
    .filter(element => element.localName.includes('-') && visible(element))
    .map(element => element.getAttribute('title') || element.getAttribute('aria-label'))
    .filter(Boolean))].slice(0, 40);
  const overlayElements = [];
  for (const element of elements) {
    if (overlayElements.length >= 5) break;
    const style = getComputedStyle(element);
    if (!['fixed', 'sticky'].includes(style.position) || !visible(element)) continue;
    const rect = element.getBoundingClientRect();
    const zIndex = Number.parseInt(style.zIndex, 10) || 0;
    if (rect.width * rect.height < 0.15 * width * height && zIndex < 1000) continue;
    if (overlayElements.some(overlay => overlay.contains(element))) continue;
    overlayElements.push(element);
  }
  const overlays = overlayElements.map(element => ({
    ...box(element),
    z: Number.parseInt(getComputedStyle(element).zIndex, 10) || 0,
    text: (element.innerText ?? '').replace(/\s+/g, ' ').trim().slice(0, 80),
  }));
  const captchaPattern = /recaptcha|hcaptcha|turnstile|challenges\.cloudflare/i;
  const captcha = elements.some(element => visible(element) && captchaPattern.test(
    `${element.localName === 'iframe' ? element.src : ''} ${element.getAttribute('class') ?? ''}`));
  return {
    viewport: [width, height], surfaces, titled_controls: titledControls, overlays, captcha,
  };
}

exports.serve = async function () {
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const writeResponse = response => process.stdout.write(JSON.stringify(response) + '\n');
  global.console = new Console({ stdout: process.stderr, stderr: process.stderr });
  let browser;
  let context;
  let page;
  let closing;
  let previousNavigation = new Set();
  const state = {};

  async function close() {
    // Close only the agent's tab, then disconnect; the attached Chrome keeps running.
    closing ??= (async () => {
      await page?.close().catch(() => {});
      await browser?.close();
    })();
    await closing;
  }

  async function terminate() {
    try {
      await close();
    } finally {
      process.exit(0);
    }
  }

  process.once('SIGTERM', terminate);
  process.once('SIGINT', terminate);
  process.once('SIGHUP', terminate);

  async function observe() {
    const session = await context.newCDPSession(page);
    let tree;
    try {
      tree = await session.send('Accessibility.getFullAXTree');
    } finally {
      await session.detach();
    }
    const title = await page.title();
    // ponytail: traversal blocks this single worker; partition only if measured latency requires it.
    const simplified = simplifyAccessibilityTree(pruneAccessibilityTree(tree), previousNavigation);
    previousNavigation = simplified.navigation;
    return {
      url: page.url(),
      title,
      accessibility_tree: simplified.tree,
      page_geometry: await page.evaluate(collectPageGeometry).catch(() => ({})),
    };
  }

  async function execute(code) {
    const execution = {
      success: true,
      stdout: '',
      result: null,
      traceback: null,
    };
    const output = new Writable({
      write(chunk, encoding, callback) {
        execution.stdout += chunk.toString();
        callback();
      },
    });
    const console = new Console({ stdout: output, stderr: output, colorMode: false });
    try {
      if (/^\s*\(\s*async\b/.test(code)) {
        throw new Error('Write an async function body, not an unawaited async wrapper.');
      }
      const run = new AsyncFunction(
        'playwright', 'browser', 'context', 'page', 'state', 'console', code,
      );
      const value = await run(playwright, browser, context, page, state, console);
      execution.result = value === undefined ? null : inspect(value, { colors: false });
    } catch (error) {
      execution.success = false;
      execution.traceback = error?.stack ?? String(error);
    }
    return execution;
  }

  async function handle(message) {
    if (!message || typeof message !== 'object' || Array.isArray(message)) {
      throw new Error('message must be a JSON object');
    }
    if (message.type === 'start') {
      if (browser) throw new Error('worker is already started');
      try {
        browser = await playwright.chromium.connectOverCDP(message.cdp_url);
        context = browser.contexts()[0];
        page = await context.newPage();
        return { ok: true, type: 'started', observation: await observe() };
      } catch (error) {
        await close();
        throw error;
      }
    }
    if (message.type === 'close') {
      await close();
      return { ok: true, type: 'closed' };
    }
    if (!page) throw new Error('worker has not been started');
    if (message.type === 'execute') {
      if (typeof message.code !== 'string') throw new Error('execute requires a string code field');
      const execution = await execute(message.code);
      return { ok: true, type: 'executed', execution, observation: await observe() };
    }
    if (message.type === 'screenshot') {
      // CSS-pixel viewport capture, so image coordinates equal page.mouse coordinates.
      const image = await page.screenshot({ type: 'jpeg', quality: 60, scale: 'css', timeout: 10000 })
        .catch(() => null);
      return { ok: true, type: 'screenshot', screenshot: image?.toString('base64') ?? null };
    }
    throw new Error(`unknown message type: ${message.type}`);
  }

  try {
    for await (const line of input) {
      if (!line.trim()) continue;
      let response;
      try {
        response = await handle(JSON.parse(line));
      } catch (error) {
        response = { ok: false, type: 'error', error: String(error) };
      }
      writeResponse(response);
      if (response.type === 'closed' && response.ok) break;
    }
  } finally {
    input.close();
    await close();
    process.removeListener('SIGTERM', terminate);
    process.removeListener('SIGINT', terminate);
    process.removeListener('SIGHUP', terminate);
  }
};
