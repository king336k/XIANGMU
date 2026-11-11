import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require=createRequire(new URL("../package.json",import.meta.url));
test("协作访问日志保留状态与耗时，不记录令牌、请求头或正文",()=>{
  const ts=require("typescript");
  const source=readFileSync(new URL("../../packages/logger/src/middleware.ts",import.meta.url),"utf8");
  const events=[],exports={};
  const resolve=(name)=>{
    if(name==="./config") return {logger:{info:(message,context)=>events.push({message,context})},loggerConfig:{}};
    if(name==="winston")return {transports:{Console:class{}}};
    if(name==="express-winston")return {default:{logger:()=>()=>events.push({unsafe:true})}};
    throw new Error(name);
  };
  new Function("require","exports",ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(resolve,exports);
  let finish,continued=false;
  exports.loggerMiddleware({method:"GET",path:"/live/health/",url:"/live/health/?token=private-canary",headers:{authorization:"Bearer private-canary",cookie:"private-canary"},body:{password:"private-canary"}}, {statusCode:200,on:(name,callback)=>{assert.equal(name,"finish");finish=callback;}},()=>{continued=true;});
  assert.equal(continued,true);finish();
  assert.equal(events.length,1);assert.equal(events[0].context.statusCode,200);
  assert.equal(events[0].context.path,"/live/health/");assert.equal(typeof events[0].context.durationMs,"number");
  assert.ok(!JSON.stringify(events).includes("private-canary"));
});
