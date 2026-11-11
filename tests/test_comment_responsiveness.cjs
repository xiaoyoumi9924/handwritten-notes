const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/markdown_to_handwrite/webui/app.js', 'utf8');
const get = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));
const code = [
  get('async function finishCommentDrag(', 'function setActiveEditTool('),
  get('async function saveComment(', 'function fitCommentPoint('),
  get('async function undoPageEdit(', 'async function resetPageEdits('),
  get('async function savePageEdits(', 'function setActiveModule('),
].join('\n');
const elements = {'#comment-text': {value:'A quick note',focus(){}}, '#save-state': {textContent:''},
 '#download-output': {classList:{add(){},remove(){}}}, '#download-png': {disabled:false}};
let fetches = 0, renders = 0;
const initial = {rotation:0,crop:null,marks:[]};
const state = {page:0,pages:['page'],jobId:'job',edits:[structuredClone(initial)], savedEdits:[structuredClone(initial)],
  editHistory:[[]],commentImages:[{}],pendingCommentPoint:[.1,.2], commentWidth:.03,editing:false,rendering:false,editSaveQueued:false, files:{}};
const context = {state, JSON, clone:structuredClone, $:s=>elements[s], fitCommentPoint:p=>p,
 pushEditHistory:p=>state.editHistory[p].push(structuredClone(state.edits[p])), closeCommentEditor(){state.pendingCommentPoint=null},
 renderPageComments(){renders++},updateUndoButton(){},drawEditPreview(){},syncEditLayer(){},showCurrentPage(){},syncMainExportButton(){},showToast(){},
 fetch:async()=>{fetches++; throw new Error('offline')}};
vm.createContext(context); vm.runInContext(code,context);
(async()=>{
 await context.saveComment();
 assert.equal(state.edits[0].marks.length,1); assert.equal(fetches,0); assert.equal(context.hasPendingPageEdits(),true);
 state.commentDrag={pointerId:2,moved:true,comment:{classList:{remove(){}},hasPointerCapture(){return false}}};
 state.edits[0].marks[0].points[0]=[.2,.3];
 await context.finishCommentDrag({pointerId:2}); assert.equal(fetches,0); assert.ok(renders>=2);
 await context.undoPageEdit(); assert.equal(fetches,0); assert.equal(state.edits[0].marks.length,0);
 state.edits[0].marks.push({kind:'comment',text:'keep this',points:[[.1,.1]],width:.03,color:'#123456'});
 assert.equal(await context.savePageEdits(),false); assert.equal(fetches,1); assert.equal(state.edits[0].marks[0].text,'keep this');
 console.log('Comment interactions stay local and failed saves retain edits');
})().catch(error=>{console.error(error);process.exitCode=1});
