const { Console } = require('node:console');
const { createInterface } = require('node:readline');
const { Writable } = require('node:stream');
const { inspect } = require('node:util');
const playwright = require('playwright');

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

exports.serve = async function () {
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const writeResponse = response => process.stdout.write(JSON.stringify(response) + '\n');
  global.console = new Console({ stdout: process.stderr, stderr: process.stderr });
  let browser;
  let context;
  let page;
  let closing;
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
    return { url: page.url(), title: await page.title(), tree };
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
        browser = await playwright.chromium.launch({ headless: false, slowMo: 250 });
        context = await browser.newContext();
        page = await context.newPage();
        await page.goto('about:blank');
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
