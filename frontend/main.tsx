import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { createPortal } from 'react-dom'
import { Activity, ArrowUpRight, BookOpen, CheckSquare2, ChevronDown, Download, Ellipsis, ExternalLink, LayoutDashboard, Link2, Menu, Monitor, Moon, MoreVertical, Search, Settings2, Share2, SlidersHorizontal, Sun, Video, WandSparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Separator } from '@/components/ui/separator'
import { Toaster } from '@/components/ui/sonner'
import { toast } from 'sonner'
import './styles.css'
import './device.css'
import './workspace.css'

declare global {
  interface Window {
    show: (view: string) => void
    applyTheme: (theme: string) => void
    ToolkitUI: { notify: (msg: string, kind?: string) => void; confirmAction: (message: string) => Promise<boolean>; openConfirm: () => void; closeConfirm: () => void }
  }
}
const pages = [
  {id:'edit',label:'Bulk Edit',icon:WandSparkles,description:'Update your video descriptions'},
  {id:'download',label:'Download',icon:Download,description:'Save videos, audio and metadata'},
  {id:'tools',label:'Tools',icon:Settings2,description:'Exports and channel utilities'},
]
const query = (s: string) => document.querySelector<HTMLElement>(s)!

function PhonePreviewLegacy({channel, view, onOpenEdit}: {channel: string; view: string; onOpenEdit: () => void}) {
  const label = ({overview:'Channel overview',videos:'Video library',edit:'Description updates',links:'Link check',download:'Downloads',tools:'Channel tools',help:'How to use'} as Record<string,string>)[view] || 'Channel overview'
  return <aside className="device-preview" aria-label="Channel Toolkit preview">
    <div className="device-preview-label"><span>Preview</span><span>{label}</span></div>
    <div className="phone-shell">
      <div className="phone-top"><img src="/assets/channel-mark.svg" alt=""/><span>Channel Toolkit</span><Share2 size={14}/></div>
      <div className="phone-profile"><span className="phone-mark"><img src="/assets/channel-mark.svg" alt=""/></span><strong>{channel}</strong><small>Your YouTube workspace</small></div>
      <div className="phone-tabs"><span className={view==='overview'?'active':''}>Home</span><span className={view==='edit'?'active':''}>Edit</span><span className={view==='videos'?'active':''}>Videos</span></div>
      <div className="phone-stack">
        <div className="phone-card"><span className="phone-card-icon"><WandSparkles size={17}/></span><div><b>Bulk Edit descriptions</b><small>Update links and handles safely</small></div><MoreVertical size={16}/></div>
        <div className="phone-card"><span className="phone-card-icon"><Video size={17}/></span><div><b>Your video library</b><small>Scan, select, and review videos</small></div><MoreVertical size={16}/></div>
        <div className="phone-card phone-card-feature"><span>Ready to review?</span><b>Preview every change first</b><button type="button" onClick={onOpenEdit}>Open Bulk Edit <ExternalLink size={13}/></button></div>
      </div>
      <div className="phone-footer">Local project · Your data stays here</div>
    </div>
  </aside>
}

// The workspace no longer has a decorative preview panel. This kept component
// preserves the portal call while ensuring the working area owns the screen.
const PhonePreview = (_: { channel: string; view: string; onOpenEdit: () => void }) => null

/** Move, never clone: native values, event handlers and IDs survive closing. */
function Moved({selector}: {selector: string}) {
  const host = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const node = query(selector)
    if (!node || !host.current) return
    const placeholder = document.createComment('dialog field home')
    const wasOpen = node.hasAttribute('open')
    if(node.tagName==='DETAILS') node.setAttribute('open','')
    node.before(placeholder); host.current.append(node)
    return () => { if(node.tagName==='DETAILS'&&!wasOpen)node.removeAttribute('open'); placeholder.replaceWith(node) }
  }, [selector])
  return <div ref={host} className="moved-fields" />
}

function App() {
  useLayoutEffect(()=>{
    const header=query('.shell-header');
    const observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--shell-header-height',`${header.getBoundingClientRect().height}px`));
    observer.observe(header);
    return ()=>observer.disconnect();
  },[])
  const [view,setView] = useState(location.hash.slice(1) || 'edit')
  const [sheet,setSheet] = useState(false)
  const [command,setCommand] = useState(false)
  const [dialog,setDialog] = useState<string | null>(null)
  const [channel,setChannel] = useState('Your local workspace')
  const [filterSummary,setFilterSummary] = useState('All videos · Newest first')
  const [confirmation,setConfirmation] = useState<{message:string;resolve:(accepted:boolean)=>void} | null>(null)
  const [updateTitle,setUpdateTitle] = useState('Confirm description updates')
  const [updateSub,setUpdateSub] = useState('')
  const lastFocused = useRef<HTMLElement | null>(null)
  const activeDialog = useRef<string | null>(null)
  activeDialog.current = dialog
  const open = (name: string) => {lastFocused.current=document.activeElement as HTMLElement;setDialog(name)}
  const navigate = (id: string) => { window.show(id); setView(id); setSheet(false); setCommand(false) }
  useEffect(() => {
    const hash = () => setView(location.hash.slice(1) || 'edit')
    const key = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase()==='k') {e.preventDefault();setCommand(v=>!v)} }
    window.addEventListener('hashchange',hash); window.addEventListener('keydown',key)
    const observer = new MutationObserver(()=>setChannel(query('#brandChannel').textContent || 'Your local workspace'))
    observer.observe(query('#brandChannel'), {childList:true,subtree:true,characterData:true})
    setChannel(query('#brandChannel').textContent || 'Your local workspace')
    query('.header-actions').prepend(query('#header-help'))
    query('.header-brand').setAttribute('href', '#edit')
    query('.shell-header').append(query('#header-quota'))
    query('button[aria-label="View activity"]').id = 'activity-toggle'
    query('#activity-toggle').setAttribute('aria-expanded', 'false')
    const activityPanel = query('#activity-panel')
    const toggleActivity = (event: Event) => {
      event.stopPropagation()
      activityPanel.toggleAttribute('data-open')
      query('#activity-toggle').setAttribute('aria-expanded', String(activityPanel.hasAttribute('data-open')))
    }
    const closeActivity = () => {
      activityPanel.removeAttribute('data-open')
      query('#activity-toggle').setAttribute('aria-expanded', 'false')
    }
    const activityToggle = query('#activity-toggle')
    activityToggle.addEventListener('click', toggleActivity, true)
    query('#activityClose').addEventListener('click', closeActivity)
    window.ToolkitUI = {
      notify: (msg,kind) => kind==='bad' ? toast.error(msg,{duration:8000}) : toast.success(msg),
      confirmAction: message => new Promise(resolve => {lastFocused.current=document.activeElement as HTMLElement;setConfirmation({message,resolve})}),
      openConfirm: () => {setUpdateTitle(query('#dlgTitle').textContent || 'Confirm');setUpdateSub(query('#dlgSub').textContent || '');open('update')},
      closeConfirm: () => setDialog(null)
    }
    return () => {observer.disconnect();activityToggle.removeEventListener('click',toggleActivity,true);query('#activityClose').removeEventListener('click',closeActivity);window.removeEventListener('hashchange',hash);window.removeEventListener('keydown',key)}
  }, [])
  const nav = <nav className="workspace-nav" aria-label="Main navigation">{pages.map(({id,label,icon:Icon})=><Button key={id} variant="ghost" aria-label={label} aria-current={view===id?'page':undefined} onClick={()=>navigate(id)} data-page={id}><span className="nav-icon"><Icon size={22}/></span><span className="nav-text">{label}</span></Button>)}</nav>
  const titles: Record<string,[string,string]> = {
    filters:['Filter & sort videos','Choose which videos to display. This does not change your selected videos.'],
    download:['Download settings','Adjust the output and optional extras. Settings are kept when you close this window.'],
    help:['How to use Bulk Edit','A preview is required before any description can be updated.'],
    export:['Export channel data','Choose a file format. The export is saved in the project folder.'],
    cookies:['Private video access','Choose a browser for yt-dlp to read signed-in cookies from.'],
    update:[updateTitle,updateSub || 'Review the scope before publishing.'],
  }
  const dialogTitle = titles[dialog || ''] || ['', '']
  function resolveConfirm(accepted:boolean) { confirmation?.resolve(accepted);setConfirmation(null) }
  return <TooltipProvider delayDuration={300}>
    {createPortal(<Button variant="ghost" className="header-help-button" aria-label="How to use" onClick={()=>navigate('help')}><BookOpen size={18}/><span>How to use</span></Button>,query('#header-help'))}
    {createPortal(<header className="shell-header"><div className="header-leading"><Button className="mobile-menu" variant="ghost" size="icon" aria-label="Open navigation" onClick={()=>setSheet(true)}><Menu/></Button><a className="header-brand" href="#overview"><img src="/assets/channel-mark.svg" width="30" height="30" alt="Channel Toolkit logo"/><span>Channel Toolkit</span></a></div><Button variant="secondary" className="workspace-switcher" onClick={()=>setCommand(true)}><img src="/assets/channel-mark.svg" alt=""/>{channel}<ChevronDown size={15}/></Button><div className="header-actions"><Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" aria-label="View activity" onClick={()=>{navigate('overview');query('#activity-card').scrollIntoView({block:'center'})}}><Activity/></Button></TooltipTrigger><TooltipContent>View activity</TooltipContent></Tooltip></div></header>,query('#shell-header'))}
    {createPortal(<aside className="desktop-sidebar"><div className="channel-identity"><span className="channel-avatar">{channel.slice(0,1).toUpperCase()}</span><div><strong>Your channel</strong><span>{channel}</span></div></div><p className="nav-label">WORKSPACE</p>{nav}<div className="sidebar-bottom"><Separator/><p>Your channel, in one place.</p><span>Changes are saved in this local project.</span></div></aside>,query('#shell-sidebar'))}
    {createPortal(<PhonePreview channel={channel} view={view} onOpenEdit={()=>navigate('edit')}/>, query('#workspace-window'))}
    <Sheet open={sheet} onOpenChange={setSheet}><SheetContent side="bottom" className="navigation-sheet"><SheetHeader><SheetTitle>Your workspace</SheetTitle><SheetDescription>{channel}</SheetDescription></SheetHeader>{nav}</SheetContent></Sheet>
    <nav className="mobile-bottom-tabs" aria-label="Quick navigation">{pages.filter(page=>['overview','edit','download'].includes(page.id)).map(({id,label,icon:Icon})=><button key={id} type="button" data-tab={id} aria-current={view===id?'page':undefined} onClick={()=>navigate(id)}><Icon size={21} strokeWidth={view===id?2.4:1.8}/><span>{label}</span></button>)}<button type="button" aria-label="More pages" aria-expanded={sheet} onClick={()=>setSheet(true)}><Ellipsis size={22}/><span>More</span></button></nav>
    <CommandDialog open={command} onOpenChange={setCommand} title="Go to a page" description="Search pages in your workspace."><CommandInput placeholder="Where would you like to go?"/><CommandList><CommandEmpty>No matching page. Try “videos” or “help”.</CommandEmpty><CommandGroup heading="Your workspace">{pages.map(({id,label,icon:Icon,description})=><CommandItem key={id} onSelect={()=>navigate(id)}><Icon/><div><strong>{label}</strong><p className="text-xs text-muted-foreground">{description}</p></div></CommandItem>)}</CommandGroup></CommandList></CommandDialog>
    {createPortal(<div className="filter-controls"><Button variant="outline" onClick={()=>open('filters')}><SlidersHorizontal/>Filter & sort</Button><Button variant="ghost" className="mobile-select-all" onClick={()=>query('#vAll').click()}><CheckSquare2/>Select all shown</Button><span className="hint">{filterSummary}</span></div>,query('#video-filter-trigger'))}
    {createPortal(<div className="settings-launcher"><div><h2>3. Fine-tune your download</h2><p className="sub">The preset fills in sensible defaults. Adjust formats, captions, filters, and output folder if needed.</p></div><Button variant="outline" onClick={()=>open('download')}><Settings2/>Download settings</Button></div>,query('#download-settings-trigger'))}
    {createPortal(<Button variant="ghost" onClick={()=>open('help')}><BookOpen/>How to use Bulk Edit</Button>,query('#edit-help-trigger'))}
    {createPortal(<Button variant="outline" onClick={()=>open('export')}>Export data<ArrowUpRight/></Button>,query('#export-trigger'))}
    {createPortal(<Button variant="outline" onClick={()=>open('cookies')}><Settings2/>Configure access</Button>,query('#cookie-trigger'))}
    <Dialog open={dialog!==null} onOpenChange={value=>{if(!value)setDialog(null)}}><DialogContent className={dialog==='download'?'settings-dialog':''} onOpenAutoFocus={event=>{if(dialog==='update'){event.preventDefault();query('#dlgWord')?.focus()}}} onCloseAutoFocus={event=>{event.preventDefault();if(activeDialog.current===null)lastFocused.current?.focus()}}><DialogHeader><DialogTitle>{dialogTitle[0]}</DialogTitle><DialogDescription>{dialogTitle[1]}</DialogDescription></DialogHeader><div className="dialog-scroll">
      {dialog==='filters'&&<Moved selector="#video-filter-fields"/>}
      {dialog==='cookies'&&<><Moved selector="#cookie-fields"/><p className="hint">Close that browser before syncing if its cookie file is locked. This setting is used by Sync metadata.</p></>}
      {dialog==='export'&&<><p className="sub">CSV works in Excel or Google Sheets. JSON preserves the complete cached metadata.</p><Moved selector="#export-fields"/></>}
      {dialog==='help'&&<Moved selector="#edit-help-fields"/>}
      {dialog==='update'&&<Moved selector="#dlg .dlg-body"/>}
      {dialog==='download'&&<Tabs defaultValue="output"><TabsList className="settings-tabs"><TabsTrigger value="output">Output</TabsTrigger><TabsTrigger value="extras">Extras</TabsTrigger><TabsTrigger value="filters">Filters</TabsTrigger><TabsTrigger value="system">System</TabsTrigger></TabsList><TabsContent value="output"><Moved selector="#download-settings-fields > .grid"/></TabsContent><TabsContent value="extras"><Moved selector="#download-settings-fields > details:first-of-type"/></TabsContent><TabsContent value="filters"><Moved selector="#download-settings-fields > details:last-of-type"/></TabsContent><TabsContent value="system"><Moved selector="#dlEnv"/></TabsContent></Tabs>}
    </div>{dialog==='update'?<Moved selector="#dlg .dlg-foot"/>:<DialogFooter><Button onClick={()=>{if(dialog==='filters'){const f=document.querySelector<HTMLSelectElement>('#vFilter')!;const s=document.querySelector<HTMLSelectElement>('#vSort')!;setFilterSummary(`${f.selectedOptions[0].text} · ${s.selectedOptions[0].text}`)}setDialog(null)}}>Done</Button></DialogFooter>}</DialogContent></Dialog>
    <AlertDialog open={!!confirmation} onOpenChange={value=>{if(!value)resolveConfirm(false)}}><AlertDialogContent onCloseAutoFocus={event=>{event.preventDefault();lastFocused.current?.focus()}}><AlertDialogHeader><AlertDialogTitle>Confirm this action</AlertDialogTitle><AlertDialogDescription className="whitespace-pre-line">{confirmation?.message}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel onClick={()=>resolveConfirm(false)}>Cancel</AlertDialogCancel><AlertDialogAction onClick={()=>resolveConfirm(true)}>Continue</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    <Toaster theme="dark" closeButton position="bottom-right" richColors/>
  </TooltipProvider>
}
createRoot(query('#ui-root')).render(<App/> )
