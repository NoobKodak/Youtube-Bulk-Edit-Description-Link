const {app, BrowserWindow, ipcMain, shell, dialog, session} = require('electron');
const {spawn,spawnSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {migrate:copyProject,completedFolder}=require('./storage.cjs');
let backend, win, origin, token, quitting=false;
let closeApproved=false;
let smokeFolder=null;
const smoke=process.argv.includes('--smoke-test');
app.setName('Channel Toolkit');
app.setPath('userData',path.join(app.getPath('appData'),'Channel Toolkit'));
const dataDir=process.env.TOOLKIT_TEST_DATA || app.getPath('userData');
if(!app.requestSingleInstanceLock()) app.quit();
else {
app.on('second-instance',()=>{if(win){win.restore();win.focus();}});
app.whenReady().then(start).catch(fail);
}
function fail(error){
  fs.mkdirSync(dataDir,{recursive:true});
  fs.appendFileSync(path.join(dataDir,'desktop.log'),`${new Date().toISOString()} ${error.stack||error}\n`);
  if(!smoke) dialog.showErrorBox('Channel Toolkit could not start',`${error.message}\n\nLogs: ${dataDir}\nClose and reopen the app. Your saved data is preserved.`);
  quitting=true;
  if(backend && backend.exitCode===null)spawnSync('taskkill',['/PID',String(backend.pid),'/T','/F'],{windowsHide:true});
  app.exit(1);
}
function migrate(source){
  copyProject(source,dataDir);
}
async function start(){
  fs.mkdirSync(dataDir,{recursive:true});
  if(!smoke && !fs.existsSync(path.join(dataDir,'migration.json'))){
    if(process.env.TOOLKIT_MIGRATE_FROM)migrate(process.env.TOOLKIT_MIGRATE_FROM);
    else {
    const chosen=await dialog.showOpenDialog({title:'Preserve your existing toolkit settings: choose the project folder (Cancel for a new workspace)',properties:['openDirectory']});
    if(!chosen.canceled)migrate(chosen.filePaths[0]);
    }
  }
  const resources=app.isPackaged?process.resourcesPath:path.resolve(__dirname,'../desktop-stage');
  const migrationFile=path.join(dataDir,'migration.json');
  const downloadDir=fs.existsSync(migrationFile)?JSON.parse(fs.readFileSync(migrationFile)).downloads:path.join(app.getPath('downloads'),'Channel Toolkit');
  token=crypto.randomBytes(32).toString('hex');
  win=new BrowserWindow({width:1440,height:960,minWidth:360,minHeight:600,backgroundColor:'#0b0b0c',show:false,webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
  win.on('close',event=>{
    if(smoke || closeApproved || !origin)return;
    event.preventDefault();
    (async()=>{
      const status=await (await fetch(origin+'/api/status',{headers:{'X-Toolkit-Token':token}})).json();
      if(['downloading','updating','scanning','syncing'].includes(status.phase)){
        const answer=await dialog.showMessageBox(win,{type:'question',buttons:['Keep working','Close and stop this job'],defaultId:0,cancelId:0,title:'A job is still running',message:'Closing Channel Toolkit will stop its current job. Keep the app open to let it finish.'});
        if(answer.response===0)return;
      }
      closeApproved=true;win.close();
    })().catch(()=>{closeApproved=true;win.close();});
  });
  win.webContents.setWindowOpenHandler(({url})=>{if(url.startsWith('https://'))shell.openExternal(url);return {action:'deny'};});
  win.webContents.on('will-navigate',(event,url)=>{if(origin && new URL(url).origin!==origin){event.preventDefault();if(url.startsWith('https://'))shell.openExternal(url);}});
  win.webContents.session.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
  await win.loadFile(path.join(__dirname,'loading.html'));win.show();
  const log=fs.openSync(path.join(dataDir,'backend.log'),'a');
  backend=spawn(path.join(resources,app.isPackaged?'backend':'toolkit-backend','toolkit-backend.exe'),[],{cwd:dataDir,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,TOOLKIT_PORT:'0',TOOLKIT_DESKTOP:'1',TOOLKIT_DATA_DIR:dataDir,TOOLKIT_DOWNLOAD_DIR:downloadDir,TOOLKIT_ACCESS_TOKEN:token,TOOLKIT_YTDLP:path.join(resources,'tools','yt-dlp.exe'),PATH:path.join(resources,'tools')+path.delimiter+process.env.PATH}});
  fs.closeSync(log);
  backend.on('error',fail);
  backend.on('exit',(code)=>{if(!quitting)fail(new Error(`The local backend stopped (${code}).`));});
  const readyFile=path.join(dataDir,'ready-'+token.slice(0,12)+'.json');
  // Backend readiness is published only after the server has bound its socket.
  const deadline=Date.now()+90000;
  while(Date.now()<deadline){if(fs.existsSync(readyFile)){origin=JSON.parse(fs.readFileSync(readyFile)).origin;fs.unlinkSync(readyFile);break;}await new Promise(r=>setTimeout(r,200));}
  if(!origin)throw new Error('The backend did not become ready within 90 seconds.');
  const status=await fetch(origin+'/api/status',{headers:{'X-Toolkit-Token':token}});if(!status.ok)throw new Error('The backend readiness check failed.');
  win.webContents.session.webRequest.onBeforeSendHeaders({urls:[origin+'/*']},(details,callback)=>{details.requestHeaders['X-Toolkit-Token']=token;callback({requestHeaders:details.requestHeaders});});
  ipcMain.handle('toolkit:open-download-folder',async event=>{
    if(event.sender!==win.webContents || new URL(event.senderFrame.url).origin!==origin)throw new Error('Untrusted folder request.');
    const status=smoke && smokeFolder ? {download:{status:'complete',folder:smokeFolder}} : await (await fetch(origin+'/api/status',{headers:{'X-Toolkit-Token':token}})).json();
    const folder=completedFolder(status.download);
    const error=await shell.openPath(folder);if(error)throw new Error(error);
  });
  await win.loadURL(origin);
  if(smoke){
    await win.webContents.executeJavaScript(`new Promise(resolve=>{const check=()=>{if(window.ToolkitUI && document.querySelector('.desktop-sidebar [data-page]'))resolve();else setTimeout(check,100)};check()})`);
    const forbidden=await fetch(origin+'/api/status');
    const checks=await win.webContents.executeJavaScript(`({title:document.title,bridge:typeof window.ToolkitDesktop?.openDownloadFolder,nav:document.querySelectorAll('.desktop-sidebar [data-page]').length,node:typeof require})`);
    const ui=await win.webContents.executeJavaScript(`(async()=>{
      show('download');renderDownloadProgress({id:'offline-test',status:'running',percent:'42.5%',item:2,items:3,title:'Mock download',folder:'mock'});
      const progress=document.querySelector('#downloadProgress progress').value;
      renderDownloadProgress({id:'offline-test',status:'complete',folder:'mock'});
      const completion=document.querySelector('#downloadComplete').open && document.querySelector('#downloadOpenFolder').textContent==='Open folder';
      document.querySelector('#downloadComplete').close();
      const pages=['edit','download','tools','links'].map(view=>{show(view);return !document.querySelector('#view-'+view).hidden});
      return {progress,completion,pages};
    })()`);
    smokeFolder=path.join(dataDir,'Mock finished files');fs.mkdirSync(smokeFolder,{recursive:true});
    await win.webContents.executeJavaScript('window.ToolkitDesktop.openDownloadFolder()');
    fs.writeFileSync(path.join(dataDir,'smoke-result.json'),JSON.stringify({checks,ui,nativeFolderOpened:true,unauthorized:forbidden.status,origin}));
    if(forbidden.status!==403 || checks.node!=='undefined' || checks.bridge!=='function' || checks.nav!==3 || ui.progress!==42.5 || !ui.completion)throw new Error('Packaged smoke checks failed.');
    app.quit();
  }
}
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',()=>{quitting=true;if(backend && backend.exitCode===null)spawnSync('taskkill',['/PID',String(backend.pid),'/T','/F'],{windowsHide:true});});
