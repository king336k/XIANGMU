import assert from 'node:assert/strict';
import{readFileSync}from'node:fs';import{createRequire}from'node:module';import test from'node:test';
const require=createRequire(new URL('../package.json',import.meta.url));const ts=require('typescript');
function load(){const code=ts.transpileModule(readFileSync(new URL('../core/components/quality/flow-graph.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;const exports={};new Function('exports',code)(exports);return exports;}
test('分叉任务保持同列，汇合节点必须位于所有前置之后',()=>{const {flowLayers}=load();const result=flowLayers([{id:'root',depends_on:[]},...['a','b','c','d'].map(id=>({id,depends_on:['root']})),{id:'f',depends_on:['a','b','c','d']},{id:'test',depends_on:['f']}]);assert.deepEqual(result.map(layer=>layer.map(node=>node.id)),[['root'],['a','b','c','d'],['f'],['test']]);});
test('循环和丢失的前置不绘制为可执行流程',()=>{const {flowLayers}=load();assert.throws(()=>flowLayers([{id:'a',depends_on:['b']},{id:'b',depends_on:['a']}]),/循环/);assert.throws(()=>flowLayers([{id:'a',depends_on:['missing']}]),/不存在/);});
test('空流程不会假造完成节点',()=>assert.deepEqual(load().flowLayers([]),[]));
