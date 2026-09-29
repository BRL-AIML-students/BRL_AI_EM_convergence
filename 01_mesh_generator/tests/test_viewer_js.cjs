const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync(path.join(__dirname, '..', 'viewer.html'), 'utf8');
const given = process.argv[2];
const start = html.indexOf('function real(token)');
const end = html.indexOf('function sizeCanvas()', start);
assert(start >= 0 && end > start, 'NAS parser must be present in viewer.html');
const parser = html.slice(start, end);
const sample = '$ length unit: mm\nGRID,1,,0.0,0.0,0.0\nGRID,2,,1.0,0.0,0.0\nGRID,3,,0.0,1.0,0.0\nCTRIA3,1,7,1,2,3\nENDDATA\n';
const actual = vm.runInNewContext(`${parser}\nparseNAS(input)`, {input: sample});
assert.equal(actual.nodeCount, 3);
assert.equal(actual.faces.length, 1);
assert.equal(actual.faces[0].pid, 7);
assert.equal(actual.unit, 'mm');
console.log('Browser NAS parser: valid sample loaded');
const fixed = [
  ['GRID','1','0','0.0','0.0','0.0'],
  ['GRID','2','0','1.0','0.0','0.0'],
  ['GRID','3','0','0.0','1.0-1','0.0'],
  ['CTRIA3','1','2','1','2','3'],
].map(card=>card.map(value=>value.padEnd(8)).join('')).join('\n')+'\nENDDATA\n';
const fixedResult = vm.runInNewContext(`${parser}\nparseNAS(input)`, {input: fixed});
assert.equal(fixedResult.faces[0].pid, 2);
assert.equal(fixedResult.nodeCount, 3);

// Exercise file-to-canvas behavior without requiring browser access.
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const context2d = {
  fills: 0, setTransform(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
  closePath(){}, fill(){this.fills++}, stroke(){}, fillText(){},
};
const classList = {toggle(){}, add(){}, remove(){}};
const elements = {
  view: {getContext:()=>context2d, addEventListener(){}, classList, width:0, height:0},
  surface: {getBoundingClientRect:()=>({width:900,height:600})},
  empty: {hidden:false, querySelector:()=>({textContent:''})},
  status: {classList, textContent:''}, stats: {textContent:''},
  file: {addEventListener(){}}, fit: {addEventListener(){}},
  edges: {checked:false, addEventListener(){}}, colors: {checked:true, addEventListener(){}},
  drop: {hidden:true},
};
const renderInput = given ? fs.readFileSync(given, 'utf8') : sample;
const renderExpected = vm.runInNewContext(`${parser}\nparseNAS(input)`, {input: renderInput});
const environment = {
  document: {getElementById:id=>elements[id]},
  window: {devicePixelRatio:1, addEventListener(){}},
  ResizeObserver: class {observe(){}},
  requestAnimationFrame: callback=>callback(),
  input: renderInput,
};
vm.runInNewContext(`${script}\nload(input,'mesh.nas')`, environment);
assert(context2d.fills >= renderExpected.faces.length, 'loading a NAS file should draw its triangles');
assert(elements.empty.hidden, 'successful load should hide the empty message');
assert(elements.stats.textContent.includes(`삼각형 ${renderExpected.faces.length.toLocaleString()}`));
console.log(`Viewer file-to-canvas path: rendered ${renderExpected.faces.length} triangles`);

if (given) {
  const result = vm.runInNewContext(`${parser}\nparseNAS(input)`, {input: fs.readFileSync(given, 'utf8')});
  console.log(`${path.basename(given)}: ${result.nodeCount} nodes, ${result.faces.length} triangles`);
}
