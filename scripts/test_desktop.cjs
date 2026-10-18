const fs=require('node:fs'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process');
const executable=process.argv[2];if(!executable)throw Error('Pass the packaged application path.');
const root=path.resolve('desktop-test-data','installed smoke '+Date.now());fs.mkdirSync(root,{recursive:true});
const env={...process.env,TOOLKIT_TEST_DATA:root};delete env.ELECTRON_RUN_AS_NODE;delete env.TOOLKIT_MIGRATE_FROM;
const occupied=net.createServer();
occupied.on('error',()=>run(false));occupied.listen(8765,'127.0.0.1',()=>run(true));
function run(ownsPort){
 const child=spawn(executable,['--smoke-test'],{env,windowsHide:true});
 const timer=setTimeout(()=>{child.kill();throw Error('Desktop smoke test timed out.');},100000);
 child.on('exit',code=>{
   clearTimeout(timer);if(ownsPort)occupied.close();
   if(code!==0)throw Error('Desktop smoke failed: '+code);
   const result=JSON.parse(fs.readFileSync(path.join(root,'smoke-result.json')));
   if(!result.nativeFolderOpened||result.unauthorized!==403||result.ui.progress!==42.5)throw Error('Desktop checks failed.');
   const endpoint=new URL(result.origin);
   if(endpoint.port==='8765')throw Error('Desktop reused the occupied browser port.');
   const socket=net.connect(Number(endpoint.port),'127.0.0.1');
   socket.once('connect',()=>{socket.destroy();throw Error('Owned backend survived shutdown.');});
   socket.once('error',()=>console.log('PASS: packaged startup, private port, session protection, sandbox, module navigation, mocked progress/completion, native Open folder and owned-backend shutdown. Results: '+root));
 });
}
