import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";
import test from "node:test";
const require=createRequire(new URL("../package.json",import.meta.url)),ts=require("typescript"),React=require("react");
function render(layout,enabled=true){
  const api={},Boundary=()=>null,DateRange=()=>null;
  const mocks={react:{...React,useMemo:fn=>fn(),useCallback:fn=>fn},"mobx-react":{observer:fn=>fn},
    "next/navigation":{useParams:()=>({projectId:"p",workspaceSlug:"w"})},"@plane/i18n":{useTranslation:()=>({t:key=>key==="date_range"?"日期范围":key})},
    "@plane/utils":{getDate:x=>new Date(x),generateWorkItemLink:()=>"/w/p/p/issues/i",cn:()=>"",shouldHighlightIssueDueDate:()=>false},
    "@/hooks/store/use-project":{useProject:()=>({getProjectById:()=>({module_view:enabled,cycle_view:enabled})})},
    "@/hooks/store/use-label":{useLabel:()=>({labelMap:{}})},"@/hooks/use-issue-layout-store":{useIssueStoreType:()=>"PROJECT"},
    "@/hooks/store/use-issues":{useIssues:()=>({issues:{}})},"@/hooks/store/estimates":{useProjectEstimates:()=>({areEstimateEnabledByProjectId:()=>true})},
    "@/hooks/store/use-project-state":{useProjectState:()=>({getStateById:()=>({})})},"@/hooks/use-platform-os":{usePlatformOS:()=>({isMobile:false})},
    "@/hooks/use-app-router":{useAppRouter:()=>({push(){}})},"./with-display-properties-HOC":{WithDisplayPropertiesHOC:Boundary},
    "@/components/dropdowns/date-range":{DateRangeDropdown:DateRange},
  };
  new Function("require","exports",ts.transpileModule(readFileSync(new URL("../core/components/issues/issue-layouts/properties/all-properties.tsx",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText)(id=>mocks[id]||(id==="react/jsx-runtime"?require(id):new Proxy({},{get:()=>()=>null})),api);
  const properties={state:true,priority:true,start_date:true,due_date:true,assignee:true,modules:true,cycle:true,labels:true,estimate:true,attachment_count:true,sub_issue_count:true,link:true};
  const tree=api.IssueProperties({issue:{id:"i",project_id:"p",start_date:"2026-11-08",target_date:"2026-11-12",assignee_ids:[],module_ids:[],label_ids:[],sub_issues_count:1,attachment_count:1,link_count:1},displayProperties:properties,activeLayout:layout});
  function walk(node,found=[]){if(!node||typeof node!=="object")return found;if(Array.isArray(node)){node.forEach(child=>walk(child,found));return found;}
    if(node.type===Boundary && node.props.shouldRenderProperty && !node.props.shouldRenderProperty(properties))return found;
    found.push(node);walk(node.props?.children,found);return found;}
  return {nodes:walk(tree),Boundary,DateRange};
}
test("拖动看板与原列表保留相同卡片属性入口，模块周期按项目开关显示",()=>{
  const list=render("list"),board=render("kanban");
  const keys=result=>result.nodes.filter(node=>node.type===result.Boundary).map(node=>node.props.displayPropertyKey);
  assert.deepEqual(keys(board),keys(list));
  for(const property of ["state","priority","assignee","modules","cycle","labels","estimate","attachment_count","sub_issue_count","link"])assert.ok(keys(board).includes(property),property);
  assert.equal(keys(render("kanban",false)).includes("modules"),false);
  assert.equal(keys(render("kanban",false)).includes("cycle"),false);
});
test("工作项日期范围工具提示使用中文，子工作项不残留同类英文",()=>{
  const result=render("kanban");const date=result.nodes.find(node=>node.type===result.DateRange);
  assert.equal(date.props.customTooltipHeading,"日期范围");
  const child=readFileSync(new URL("../core/components/issues/issue-detail-widgets/sub-issues/issues-list/properties.tsx",import.meta.url),"utf8");
  assert.ok(!child.includes('customTooltipHeading="Date Range"'));
});
