const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/markdown_to_handwrite/webui/app.js','utf8');
const code = source.slice(source.indexOf('async function saveTextExport()'),source.indexOf('function movePage('));
let steps = [];
const state = {editing:false,rendering:false,pages:['x'],outputFormat:'pdf',files:{pdf:'/old.pdf'}};
const context = {state, hasPendingPageEdits:()=>true,
 savePageEdits:async()=>{steps.push('save'); state.files.pdf='/current.pdf';return true},
 window:{showSaveFilePicker:async()=>{steps.push('picker');return {name:'out.pdf',createWritable:async()=>({write:async()=>steps.push('write'),close:async()=>{},abort:async()=>{}})}}},
 fetch:async url=>{steps.push(url);return {ok:true,blob:async()=>new Blob(['pdf'])}},
 addExportRecord:()=>{},showToast:()=>{}, Blob};
vm.createContext(context);vm.runInContext(code,context);
(async()=>{await context.saveTextExport(); assert.deepEqual(steps,['picker','save','/current.pdf','write']);
 steps=[];context.savePageEdits=async()=>false;await context.saveTextExport();assert.deepEqual(steps,['picker']);
 console.log('Export saves pending edits and never exports stale files on failure');})().catch(e=>{console.error(e);process.exitCode=1});
