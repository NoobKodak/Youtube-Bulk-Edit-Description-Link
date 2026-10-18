const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('ToolkitDesktop',Object.freeze({openDownloadFolder:()=>ipcRenderer.invoke('toolkit:open-download-folder')}));
