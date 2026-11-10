const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/markdown_to_handwrite/webui/app.js', 'utf8');
const part = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));
const context = vm.createContext({
  state: { scanMode: 'smart', scanOrientation: 'auto', scanPages: [], scanPage: 0 },
  scanRequest: async () => ({ processed: true, url: '/new.webp' }),
});
vm.runInContext(part('function scanSettingsKey(', 'function renderScanFilterImages(') +
  part('async function processOneScan(', 'async function startScan('), context);

(async () => {
  const page = { scanId: 'test', rotation: 0, crop: null, processed: false };
  await context.processOneScan(page);
  assert.equal(context.scanPageReady(page), true);
  context.state.scanMode = 'bw';
  assert.equal(context.scanPageReady(page), false, 'changing mode invalidates old export');
  context.scanRequest = async () => { throw new Error('processing failed'); };
  await assert.rejects(context.processOneScan(page), /processing failed/);
  assert.equal(context.scanPageReady(page), false, 'failed conversion must not export old pixels');
  context.scanRequest = async () => ({ processed: true, url: '/bw.webp' });
  await context.processOneScan(page);
  assert.equal(context.scanPageReady(page), true, 'retry restores ready state');
  page.rotation = 90;
  assert.equal(context.scanPageReady(page), false, 'geometry changes invalidate result');

  // Changing crop while an old thumbnail request is in flight must not put
  // stale geometry into the current preview cards.
  vm.runInContext(part('async function loadScanFilterPreviews(', 'async function processOneScan('), context);
  context.renderScanFilterImages = () => {};
  context.$$ = () => [{ dataset: { scanMode: 'smart' } }];
  context.state.scanPages = [page];
  const pending = [];
  context.scanRequest = (route, options) => new Promise(resolve => pending.push({ resolve, options }));
  const oldPreview = context.loadScanFilterPreviews(page);
  page.crop = [0, 0, 0.5, 0.5];
  const newPreview = context.loadScanFilterPreviews(page);
  assert.equal(pending.length, 2);
  pending[1].resolve({ url: '/new-crop.webp' });
  await newPreview;
  pending[0].resolve({ url: '/old-crop.webp' });
  await oldPreview;
  assert.equal(page.filterPreviews.smart, '/new-crop.webp');
  vm.runInContext(part('function validScanCorners(', 'function drawScanCorners('), context);
  assert.equal(context.validScanCorners([[0,0],[1,0],[1,1],[0,1]]), true);
  assert.equal(context.validScanCorners([[0,0],[1,1],[1,0],[0,1]]), false);
  assert.equal(context.validScanCorners([[0,0],[.01,0],[.01,.01],[0,.01]]), false);
  page.appliedSettings = context.scanSettingsKey(page);
  assert.equal(context.scanPageReady(page), true);
  page.corners = [[.1,.1],[.9,.1],[.9,.9],[.1,.9]];
  assert.equal(context.scanPageReady(page), false, 'manual corners invalidate previous export');
  page.appliedSettings = context.scanSettingsKey(page);
  page.appliedMode = 'remove_handwriting';
  page.marks = [{kind:'restore',rect:[.1,.1,.2,.2]}];
  context.setScanBusy = () => {};
  context.showScanPage = () => {};
  context.showToast = () => {};
  context.scanRequest = async () => ({url:'/restored.webp'});
  await context.refreshScanRestoration(page);
  assert.equal(page.restoredUrl, '/restored.webp');
  assert.equal(context.scanPageReady(page), true);
  context.scanRequest = async () => {throw new Error('restore failed');};
  await context.refreshScanRestoration(page);
  assert.equal(context.scanPageReady(page), false, 'restoration failure blocks stale export');
  page.marks = [];
  await context.refreshScanRestoration(page);
  assert.equal(context.scanPageReady(page), true, 'undo failed restoration restores export readiness');
  assert.equal(page.restoredUrl, null);
  // Import immediately produces an export-ready page, and a failed page stays editable.
  vm.runInContext(part('async function uploadScanFiles(', 'async function scanRequest('), context);
  context.$ = () => ({ textContent: '' });
  context.scanBase64 = () => 'image-bytes';
  context.MAX_SCAN_FILE_BYTES = 18 * 1024 * 1024;
  context.fetch = async () => ({ ok: true, json: async () => ({ scanId: 'fresh', filename: 'page.jpg', url: '/raw.webp', detected: true, corners: [[0,0],[1,0],[1,1],[0,1]] }) });
  context.updateScanControls = () => {};
  context.showScanPage = () => {};
  context.showToast = () => {};
  context.setScanBusy = () => {};
  context.state.scanPages = [];
  context.processOneScan = async (uploaded) => {
    uploaded.processed = true;
    uploaded.url = '/processed.webp';
    uploaded.appliedSettings = context.scanSettingsKey(uploaded);
  };
  const imported = { name: 'page.jpg', size: 4, arrayBuffer: async () => new ArrayBuffer(4) };
  await context.uploadScanFiles([imported]);
  assert.equal(context.state.scanPages[0].url, '/processed.webp');
  assert.equal(context.scanPageReady(context.state.scanPages[0]), true);
  context.processOneScan = async () => { throw new Error('conversion failed'); };
  await context.uploadScanFiles([imported]);
  assert.equal(context.state.scanPages.length, 2);
  assert.equal(context.state.scanPages[1].processed, false);
  assert.match(context.state.scanPages[1].warning, /重新扫描/);
  console.log('Scan state regression checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
