const fs=require('node:fs');
const path=require('node:path');
function copyMissing(source,destination){
  if(!fs.existsSync(source))return;
  const stat=fs.lstatSync(source);
  if(stat.isSymbolicLink())return;
  if(stat.isDirectory()){
    fs.mkdirSync(destination,{recursive:true});
    for(const file of fs.readdirSync(source))copyMissing(path.join(source,file),path.join(destination,file));
  }else if(stat.isFile()&&!fs.existsSync(destination))fs.copyFileSync(source,destination,fs.constants.COPYFILE_EXCL);
}
function migrate(source,dataDir){
  if(!source || !fs.existsSync(source))throw new Error('The selected project folder does not exist.');
  fs.mkdirSync(dataDir,{recursive:true});
  const files=['client_secret.json','token.json','rules.json','update_progress.json','ytdlp_cache.json','youtube_descriptions_backup.json','oversize_backup.json','channel_export.csv','channel_export.json','backups','thumbnails'];
  for(const file of files)copyMissing(path.join(source,file),path.join(dataDir,file));
  fs.writeFileSync(path.join(dataDir,'migration.json'),JSON.stringify({source,downloads:path.join(source,'downloads'),date:new Date().toISOString()}));
}
function completedFolder(download){
  if(!download || download.status==='running' || !path.isAbsolute(download.folder||'') || !fs.existsSync(download.folder) || !fs.statSync(download.folder).isDirectory())throw new Error('Finish a download first to open its output folder.');
  return download.folder;
}
module.exports={migrate,completedFolder};
