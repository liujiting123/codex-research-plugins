// A short-lived CDP command or a plugin-child watcher. Connects to loopback only.
import fs from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {applyExpression, statusExpression, PAUSE_EXPRESSION, buildAppTheme, appThemeExpression} from "./skin.mjs";

export function isHostTarget(target, appPath = null) {
  if (target.type !== "page" || typeof target.url !== "string") return false;
  // Exclude plugin iframes, browser tabs, splash pages and developer tools.
  if (/^app:\/\/-\/(?:index|detached-window)\.html(?:[?#]|$)/.test(target.url)) return true;
  if (!appPath) return false;
  try {
    const url = new URL(target.url);
    const file = fileURLToPath(url);
    return file.startsWith(path.resolve(appPath) + "/Contents/Resources/") &&
      /\/webview\/(?:index|detached-window)\.html$/.test(file);
  } catch {return false;}
}

export function isAppTarget(target) {
  if (!["page", "webview"].includes(target.type) || typeof target.url !== "string") return false;
  let url;try {url=new URL(target.url);} catch {return false;}
  return (target.type === "webview" && url.protocol === "codex-sandbox:" &&
    /^mcp-app-[a-f0-9]+\.web-sandbox\.oaiusercontent\.com$/.test(url.hostname)) ||
    (["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) &&
    (url.protocol === "http:" && url.port === "8771" || url.protocol === "https:" && url.port === "8772") &&
    ["/", "/index.html"].includes(url.pathname));
}

async function publishAppTheme(dir, context) {
  const file=path.join(dir,"app-theme.json"),data=JSON.stringify(context);
  try {if(await fs.readFile(file,"utf8")===data)return;} catch {}
  await fs.mkdir(dir,{recursive:true});
  const tmp=path.join(dir,`.app-theme-${process.pid}.json`);
  await fs.writeFile(tmp,data,{mode:0o600});
  await fs.rename(tmp,file);
}

function loopbackWs(raw, port) {
  const url = new URL(raw);
  if (url.protocol !== "ws:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || Number(url.port) !== port || !url.pathname.startsWith("/devtools/page/")) {
    throw new Error("non-loopback-debug-target");
  }
  return url.href;
}

export async function evaluate(wsUrl, expression, port) {
  const ws = new WebSocket(loopbackWs(wsUrl, port));
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("debug-connect-timeout")), 1800);
      ws.addEventListener("open", () => {clearTimeout(timer);resolve();}, {once:true});
      ws.addEventListener("error", () => {clearTimeout(timer);reject(new Error("debug-connect-error"));}, {once:true});
    });
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("debug-evaluate-timeout")), 2500);
      ws.addEventListener("message", event => {
        let data;try {data=JSON.parse(String(event.data));} catch {return;}
        if (data.id !== 1) return;
        clearTimeout(timer);
        if (data.error || data.result?.exceptionDetails) {reject(new Error("skin-evaluate-error"));return;}
        resolve(data.result?.result?.value || {applied:false});
      });
      ws.send(JSON.stringify({id:1,method:"Runtime.evaluate",params:{expression,returnByValue:true,awaitPromise:true}}));
    });
  } finally {ws.close();}
}

export async function run(command, stateDir, port, appPath = null) {
  const status = {phase:"waiting",connected:false,applied:false,port,checkedAt:new Date().toISOString(),
                  message:"换肤连接未开启，当前无法直接应用；首次连接需要重新打开一次 Codex。"};
  let config;
  if (command !== "pause") {
    try {config=JSON.parse(await fs.readFile(path.join(stateDir,"skin.json"),"utf8"));}
    catch {return {...status,phase:"error",message:"没有有效的插件皮肤设置"};}
    if (!config.enabled) {await publishAppTheme(stateDir,{enabled:false});return {...status,phase:"paused",message:"自动换肤已暂停"};}
  }
  const appTheme=command === "pause"?{enabled:false}:buildAppTheme(config);
  await publishAppTheme(stateDir,appTheme);
  let targets,appTargets;
  try {
    const response = await fetch(`http://127.0.0.1:${port}/json/list`, {signal:AbortSignal.timeout(1500),redirect:"error"});
    if (!response.ok) throw new Error("debug-targets-error");
    const data = await response.json();
    if (!Array.isArray(data)) throw new Error("debug-targets-error");
    targets = data.filter(target => isHostTarget(target, appPath)).slice(0, 6);
    appTargets = data.filter(isAppTarget);
  } catch {return command === "pause" ? {...status,phase:"paused",message:"已停止自动换肤；当前窗口未连接，未确认即时还原"} : status;}
  if (!targets.length) return {...status,phase:"unsupported",message:"端口可连接，但没有找到 Codex 主窗口；尚未应用"};
  status.connected=true;status.targetCount=targets.length;
  const appResults=await Promise.allSettled(appTargets.map(target=>evaluate(target.webSocketDebuggerUrl,appThemeExpression(appTheme),port)));
  status.appTargetCount=appTargets.length;
  status.appAppliedCount=appResults.filter(result=>result.status==="fulfilled"&&(result.value.applied||result.value.removed)).length;
  let applied=0,removed=0,compatibility={};
  const results = await Promise.allSettled(targets.map(async target => {
    try {
      if(command === "ensure") {
        const current=await evaluate(target.webSocketDebuggerUrl,statusExpression(config.fingerprint),port);
        if(current.applied)return current;
      }
      return await evaluate(target.webSocketDebuggerUrl, command === "pause" ? PAUSE_EXPRESSION : applyExpression(config), port);
    } catch {return {}; /* Never log target URLs, titles or page contents. */}
  }));
  for (const result of results) {
    const value=result.status === "fulfilled"?result.value:{};
    if(value.applied){applied++;compatibility=value.compatibility || {};}
    if(value.removed)removed++;
  }
  if(command === "pause") return {...status,phase:removed===targets.length?"paused":"error",applied:false,
                                  message:removed===targets.length?"已还原当前窗口，自动换肤已暂停":"已停止自动换肤，部分窗口尚未确认还原"};
  return {...status,phase:applied===targets.length?"applied":applied?"partial":"error",applied:applied>0,
          themeId:config.themeId,compatibility,
          message:applied===targets.length?`已应用「${config.name}」到 ${applied} 个主窗口`:applied?"部分窗口已应用，其他窗口尚未就绪":"主窗口已连接，但尚未确认换肤成功"};
}

async function writeStatus(dir,status) {
  await fs.mkdir(dir,{recursive:true});
  const tmp=path.join(dir,`.runtime-status-${process.pid}.json`);
  await fs.writeFile(tmp,JSON.stringify(status));
  await fs.rename(tmp,path.join(dir,"runtime-status.json"));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const [command,...args]=process.argv.slice(2);
  const get=key=>args[args.indexOf(key)+1];
  const stateDir=get("--state-dir"),port=Number(get("--port"));
  const appPath=args.includes("--app-path")?get("--app-path"):null;
  const ownerPid=args.includes("--owner-pid")?Number(get("--owner-pid")):null;
  if(!["apply","pause","watch"].includes(command)||!stateDir||!Number.isInteger(port)||port<1024||port>65535) {
    process.stderr.write("Invalid skin engine arguments\n");process.exitCode=2;
  } else if(command === "watch") {
    if(ownerPid!==null&&(!Number.isInteger(ownerPid)||ownerPid<=0))throw new Error("invalid-owner-pid");
    const ownerAlive=()=>{if(ownerPid===null)return true;try{process.kill(ownerPid,0);return true;}catch(error){return error.code==="EPERM";}};
    let stopped=false;process.on("SIGTERM",()=>{stopped=true;});process.on("SIGINT",()=>{stopped=true;});
    while(!stopped&&ownerAlive()) {
      try {await writeStatus(stateDir,await run("ensure",stateDir,port,appPath));} catch { /* retry only while plugin is alive */ }
      await new Promise(resolve=>setTimeout(resolve,5000));
    }
  } else {
    try {process.stdout.write(JSON.stringify(await run(command,stateDir,port,appPath)));}
    catch {process.stdout.write(JSON.stringify({phase:"error",connected:false,applied:false,message:"换肤引擎执行失败"}));process.exitCode=1;}
  }
}
