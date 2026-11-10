const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/markdown_to_handwrite/webui/app.js', 'utf8');
const html = fs.readFileSync('src/markdown_to_handwrite/webui/index.html', 'utf8');
const section = source.slice(source.indexOf('async function uploadScanFiles('), source.indexOf('async function ', source.indexOf('async function uploadScanFiles(') + 1));
const sent = [];
const notices = [];
const context = vm.createContext({
  state: {scanPages: [], scanPage: 0}, MAX_SCAN_FILE_BYTES: 18 * 1024 * 1024,
  setScanBusy() {}, showScanPage() {}, updateScanControls() {},
  showToast(...args) {notices.push(args)}, scanBase64() {return 'AA=='},
  $() {return {textContent: ''}},
  async fetch(url, options) {
    const {filename} = JSON.parse(options.body); sent.push(filename);
    return {ok: true, async json() {return {scanId: 'test', filename, url: '/preview'}}};
  },
});
vm.runInContext(section, context);
(async () => {
  const files = ['IMG.HEIC', 'image.heif', 'image.PNG', 'image.jpg'].map(name => ({name, size: 1, async arrayBuffer() {return new ArrayBuffer(1)}}));
  await context.uploadScanFiles(files);
  assert.deepEqual(sent, files.map(file => file.name));
  assert.equal(context.state.scanPages.length, 4);
  assert.match(html, /accept="[^"]*\.heic[^\"]*\.heif/i);
  await context.uploadScanFiles([{name: 'bad.txt', size: 1}]);
  assert.equal(sent.length, 4);
  assert.equal(notices.at(-1)[0], '图片格式不支持');
  console.log('Scan upload format checks passed');
})().catch(error => {console.error(error); process.exitCode = 1});
