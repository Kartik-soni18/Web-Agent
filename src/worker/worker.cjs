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

function countNodes(nodes) {
  return nodes.reduce((count, node) => count + 1 + countNodes(node.children ?? []), 0);
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
    closing ??= browser ? browser.close() : Promise.resolve();
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
      raw_node_count: tree.nodes.length,
      kept_node_count: countNodes(simplified.tree.nodes),
    };
  }

  async function execute(code) {
    const execution = {
      success: true,
      stdout: '',
      result: null,
      traceback: null,
      timed_out: false,
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
        if (message.cdp_url) {
          // Attach to an externally owned browser (e.g. a BrowserGym task page); close() only disconnects.
          browser = await playwright.chromium.connectOverCDP(message.cdp_url);
          context = browser.contexts()[0];
          page = context.pages().at(-1);
        } else {
          browser = await playwright.chromium.launch({ headless: false, slowMo:600 });
          context = await browser.newContext();
          page = await context.newPage();
          await page.goto('about:blank');
        }
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
    if (message.type === 'observe') {
      return { ok: true, type: 'observed', observation: await observe() };
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
