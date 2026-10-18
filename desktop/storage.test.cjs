const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {migrate,completedFolder}=require('./storage.cjs');
test('migration preserves existing settings and backups, copies missing files and leaves downloads in place',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'Toolkit storage test '));
 const source=path.join(root,'project with spaces'),dest=path.join(root,'user data');
 fs.mkdirSync(path.join(source,'backups'),{recursive:true});fs.mkdirSync(path.join(source,'downloads'));fs.mkdirSync(path.join(dest,'backups'),{recursive:true});
 fs.writeFileSync(path.join(source,'rules.json'),'source');fs.writeFileSync(path.join(dest,'rules.json'),'saved');
 fs.writeFileSync(path.join(source,'token.json'),'mock token');fs.writeFileSync(path.join(source,'backups','same.json'),'source backup');fs.writeFileSync(path.join(dest,'backups','same.json'),'existing backup');fs.writeFileSync(path.join(source,'backups','new.json'),'new backup');
 migrate(source,dest);migrate(source,dest);
 assert.equal(fs.readFileSync(path.join(dest,'rules.json'),'utf8'),'saved');assert.equal(fs.readFileSync(path.join(dest,'token.json'),'utf8'),'mock token');assert.equal(fs.readFileSync(path.join(dest,'backups','same.json'),'utf8'),'existing backup');assert.equal(fs.readFileSync(path.join(dest,'backups','new.json'),'utf8'),'new backup');assert(!fs.existsSync(path.join(dest,'downloads')));assert(fs.existsSync(path.join(source,'token.json')));
 assert.equal(completedFolder({status:'complete',folder:path.join(source,'downloads')}),path.join(source,'downloads'));
 assert.throws(()=>completedFolder({status:'running',folder:source}));assert.throws(()=>completedFolder({status:'complete',folder:'relative'}));
 fs.rmSync(root,{recursive:true});
});
