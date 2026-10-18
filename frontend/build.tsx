/** Build the existing DOM controller's page from source-owned shadcn components.
 * IDs, native values and event attributes are kept: no API logic lives here.
 */
import fs from 'node:fs'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { parseHTML } from 'linkedom'
import { Button } from './components/ui/button'
import { Input } from './components/ui/input'
import { Textarea } from './components/ui/textarea'
import { Card } from './components/ui/card'

let source = fs.readFileSync('frontend/template.html', 'utf8')
source = source.replace(/<style>[\s\S]*?<\/style>/g, '')
  .replace('/assets/brand.css', '/assets/ui/ui.css')
const { document } = parseHTML(source)
const q = (s: string) => document.querySelector(s)!
function mount(id: string, before: Element) {
  const el = document.createElement('div'); el.id = id; before.before(el); return el
}
q('.masthead').remove()
mount('shell-header', q('.app'))
mount('shell-sidebar', q('.sidebar'))
const windowFrame = document.createElement('div')
windowFrame.id = 'workspace-window'
q('#shell-header').before(windowFrame)
windowFrame.append(q('#shell-header'), q('.app'))
q('.sidebar').setAttribute('hidden', '') // Controller hooks stay available.
q('#view-overview h1').textContent = 'Channel overview'
q('#view-edit h1').textContent = 'Bulk Edit'
q('#view-overview .eyebrow').textContent = 'Your workspace'
q('#view-edit .eyebrow').textContent = 'Description editor'
const hero = q('#view-overview > .card')
hero.className = 'home-hero'
hero.removeAttribute('style')
for (const section of document.querySelectorAll('.content > section')) {
  section.querySelector('.row:first-child')?.classList.add('page-intro')
}
const guide = q('#view-help .grid.g-2')
for (const [index, card] of [...guide.children].entries()) {
  const disclosure = document.createElement('details')
  disclosure.className = 'guide-step'
  if(index === 0) disclosure.setAttribute('open', '')
  const heading = card.querySelector('h2')!
  const summary = document.createElement('summary')
  summary.textContent = heading.textContent
  heading.remove()
  card.replaceWith(disclosure)
  disclosure.append(summary, card)
}
q('#phaseMsg').setAttribute('role', 'status')
q('.main').setAttribute('role', 'main')
q('#rErrors').setAttribute('role', 'alert')
q('#applyHelp').setAttribute('aria-live', 'polite')
q('#rApply').setAttribute('aria-describedby', 'applyHelp')
q('#btnScanApi').classList.remove('primary')
const taskStatus = document.createElement('div')
taskStatus.className = 'task-status'
taskStatus.append(q('#phaseBadge'), q('#phaseMsg'))
q('.topbar').prepend(taskStatus)
const channelActions = document.createElement('div')
channelActions.className = 'channel-actions'
for (const [id, description] of [['btnScanApi','Required before editing descriptions'], ['btnSyncFree','Optional: refresh views, likes & metadata']]) {
  const action = document.createElement('div')
  action.className = 'channel-action'
  action.append(q('#'+id))
  const helper = document.createElement('span')
  helper.className = 'action-help'
  helper.textContent = description
  action.append(helper)
  channelActions.append(action)
}
q('.topbar').append(channelActions)
q('.topbar').classList.add('bulk-channel-controls')
q('#view-edit .page-heading').after(q('.topbar'))
q('#btnScanApi').classList.add('primary')
q('#btnStop').setAttribute('hidden', '')
const headerQuota = document.createElement('div')
headerQuota.id = 'header-quota'
headerQuota.setAttribute('role', 'status')
headerQuota.setAttribute('aria-label', 'API quota today')
headerQuota.innerHTML = '<span class="quota-label">API quota today</span><span class="quota-meter"><i id="headerQuotaBar"></i></span><span id="headerQuotaText">Loading quota…</span>'
q('#shell-header').append(headerQuota)
const quotaReset = document.createElement('span')
quotaReset.id = 'headerQuotaReset'
quotaReset.textContent = 'Checking reset time…'
headerQuota.append(quotaReset)
const headerHelp = document.createElement('div')
headerHelp.id = 'header-help'
q('#shell-header').append(headerHelp)

// Keep long, secondary forms mounted in a hidden parking area between dialogs.
const parking = document.createElement('div'); parking.id = 'ui-parking'; parking.hidden = true
document.body.append(parking)
function park(node: Element, id: string) { node.id = id; parking.append(node) }
function trigger(before: Element, id: string) { mount(id, before) }
const filterRow = q('#vFilter').parentElement!.parentElement!
const filters = document.createElement('div'); filters.className = 'grid g-2'
filters.append(q('#vFilter').parentElement!, q('#vSort').parentElement!)
park(filters, 'video-filter-fields')
const filterHost = document.createElement('div'); filterHost.id = 'video-filter-trigger'; filterRow.append(filterHost)
const options = q('#dlMode').closest('.card')!
trigger(options, 'download-settings-trigger')
park(options, 'download-settings-fields')
q('#download-settings-fields h2').remove()
park(q('#dlEnv'), 'dlEnv')
const aside = q('.edit-aside')
const editBadge = q('#view-edit .page-heading > .badge')
trigger(editBadge, 'edit-help-trigger'); editBadge.remove(); park(aside, 'edit-help-fields')
q('.edit-layout').classList.add('focused-editor')
const exportRow = q('#tCsv').parentElement!
trigger(exportRow, 'export-trigger'); park(exportRow, 'export-fields')
const cookieFields = q('#tCookies').parentElement!
trigger(cookieFields, 'cookie-trigger'); park(cookieFields, 'cookie-fields')
const setup = [...document.querySelectorAll('#view-overview .card')].find(n => n.querySelector('h2')?.textContent === 'Getting started')!
const setupDetails = document.createElement('details'); setupDetails.className = 'setup-guide'
setupDetails.innerHTML = '<summary>First time here? Start with this quick guide</summary>'
setup.replaceWith(setupDetails); setup.querySelector('h2')!.remove(); setupDetails.append(setup)
q('#log').closest('.card')!.id = 'activity-card'
const activityPanel = document.createElement('aside')
activityPanel.id = 'activity-panel'
activityPanel.setAttribute('aria-label', 'Activity')
activityPanel.innerHTML = '<div class="activity-panel-head"><div><p class="eyebrow">Workspace activity</p><h2>Recent activity</h2></div><button id="activityClose" type="button" aria-label="Close activity panel">×</button></div>'
activityPanel.append(q('#activity-card'))
windowFrame.append(activityPanel)
q('#activityClose').textContent = 'Minimize'
q('#activityClose').setAttribute('aria-label', 'Minimize activity sidebar')

const editModules = document.createElement('nav')
editModules.className = 'bulk-submodules'
editModules.setAttribute('aria-label', 'Bulk Edit sections')
editModules.innerHTML = '<a href="#edit" aria-current="page">Description changes</a><a href="#links">Check links</a>'
q('#view-edit .page-heading').after(editModules)
const linksReturn = document.createElement('a')
linksReturn.className = 'back-to-bulk'
linksReturn.href = '#edit'
linksReturn.textContent = '← Back to Bulk Edit'
q('#view-links .page-intro').before(linksReturn)
q('#view-links h1').textContent = 'Links in your descriptions'
q('#view-links .sub').textContent = 'See which websites your channel points to, and find links you may want to update.'
q('#view-links > .note').textContent = 'This list shows where links appear. It does not check whether a website is working.'
q('#dlgGo').textContent = 'Apply changes'
q('#chooseVideos').textContent = 'How video scope works'
q('#editResult').before(q('.review-bar'))

// A focused editor: scope, replacements, preview, then confirmation.
q('#view-edit .steps').setAttribute('hidden', '')
q('#view-edit .edit-main > .card:first-child').classList.add('scope-summary')
q('#view-edit .section-head h2').textContent = '1. Your video scope'
q('#view-edit .edit-main > .card:nth-child(2)').classList.add('replacement-editor')
q('#view-edit .replacement-editor h2').textContent = '2. Enter your replacement'
q('#view-edit .replacement-editor .sub').textContent = 'Find text in your descriptions and replace it. Everything outside the matching text stays the same.'
q('#view-edit .review-bar b').textContent = '4. Confirm your update'
q('#view-edit #editResult').before(q('#view-edit .review-bar'))
const reviewSection = document.createElement('details')
reviewSection.className = 'bulk-review-section'
reviewSection.setAttribute('open', '')
reviewSection.innerHTML = '<summary><span><strong>3. Review &amp; confirm</strong><small>Check the results, then apply the reviewed changes.</small></span><span class="review-disclosure" aria-hidden="true">⌄</span></summary>'
q('#view-edit #editResult').before(reviewSection)
reviewSection.append(q('#editResult'), q('#view-edit .review-bar'))
const reviewHeading = document.createElement('div')
reviewHeading.className = 'review-heading-actions'
reviewSection.before(reviewHeading)
reviewHeading.append(q('#rApply'))
reviewSection.append(reviewHeading)
q('#view-edit .review-bar b').textContent = 'Update status'
const editSetup = document.createElement('div')
editSetup.className = 'bulk-setup-column'
q('#view-edit .scope-summary').before(editSetup)
editSetup.append(q('#view-edit .scope-summary'), q('#view-edit .replacement-editor'))
q('#view-download .page-intro .sub').textContent = 'Save your videos, audio, or supporting files in three simple steps.'
q('#view-download > .note').innerHTML = 'Download content you own or have permission to save.'
q('#dlSelected').setAttribute('hidden', '')
q('#dlUrls').closest('.card')!.classList.add('download-source')
q('#dlPresets').closest('.card')!.classList.add('download-presets')
q('#view-download .download-source h2').textContent = '1. Add your YouTube links'
q('#view-download .download-presets h2').textContent = '2. Choose what to save'
const downloadLayout = document.createElement('div')
downloadLayout.className = 'download-workspace'
const downloadSetup = document.createElement('div')
downloadSetup.className = 'download-setup-panel'
const downloadResults = document.createElement('aside')
downloadResults.className = 'download-results-panel'
downloadResults.setAttribute('aria-label', 'Download progress and results')
downloadResults.innerHTML = '<h2>Download progress</h2><p class="sub">Follow your download here. Finished files will be available in your output folder.</p><div id="downloadProgress"><div class="download-idle"><h3>Ready when you are</h3><p>Add your links, choose a preset, and start the download.</p></div></div>'
const downloadRun = q('#dlStart').closest('.card')!
q('#view-download .download-source').before(downloadLayout)
downloadSetup.append(q('#view-download .download-source'), q('#view-download .download-presets'), q('#download-settings-trigger'))
const downloadDestination = document.createElement('div')
downloadDestination.className = 'card download-destination'
downloadDestination.innerHTML = '<h2>3. Choose a destination</h2><p class="sub">Enter a folder on your computer. It will be created if it does not exist.</p>'
const destinationField = q('#dlOutDir').parentElement!
destinationField.querySelector('label')!.textContent = 'Save downloads to'
q('#dlOutDir').setAttribute('placeholder', 'e.g. E:\\Downloads\\YouTube')
downloadDestination.append(destinationField)
downloadSetup.insertBefore(downloadDestination, q('#download-settings-trigger'))
downloadResults.append(downloadRun)
downloadLayout.append(downloadSetup, downloadResults)
downloadRun.querySelector('h2')!.textContent = 'Start & inspect'
// Dashboard is retired. Keep its data hooks out of the interface so polling
// continues to populate the shared header quota without breaking existing IDs.
const dashboardHooks = document.createElement('div')
dashboardHooks.id = 'dashboard-data-hooks'
dashboardHooks.hidden = true
dashboardHooks.append(...q('#view-overview').children)
parking.append(dashboardHooks)
q('#view-overview').remove()
q('#nav button[data-view="overview"]').remove()

// Use genuine shadcn markup without giving React ownership of live form state.
for (const el of [...document.querySelectorAll('button, input:not([type=checkbox]):not([type=radio]), textarea, .card')].reverse()) {
  const tag = el.tagName.toLowerCase()
  let output: string
  if (tag === 'button') {
    const variant = el.classList.contains('primary') || el.classList.contains('accent') ? 'default' : el.classList.contains('danger') ? 'destructive' : el.classList.contains('ghost') ? 'ghost' : 'outline'
    output = renderToStaticMarkup(<Button variant={variant} dangerouslySetInnerHTML={{__html:el.innerHTML}} />)
  } else if (tag === 'input') output = renderToStaticMarkup(<Input />)
  else if (tag === 'textarea') output = renderToStaticMarkup(<Textarea defaultValue={el.textContent || ''} />)
  else output = renderToStaticMarkup(<Card dangerouslySetInnerHTML={{__html:el.innerHTML}} />)
  const fragment = document.createElement('template'); fragment.innerHTML = output
  const replacement = fragment.content.firstElementChild!
  const componentClass = replacement.getAttribute('class') || ''
  for (const a of [...el.attributes]) replacement.setAttribute(a.name, a.value)
  replacement.setAttribute('class', componentClass + ' ' + (el.getAttribute('class') || ''))
  el.replaceWith(replacement)
}
const runtime = document.createElement('script'); runtime.src = '/assets/ui/ui.js'
q('script[src="/app.js"]').setAttribute('defer', '')
q('script[src="/app.js"]').after(runtime)
const root = document.createElement('div'); root.id = 'ui-root'; document.body.append(root)
// The runtime executes after the root exists.
runtime.setAttribute('defer', '')
fs.writeFileSync('ui.html', '<!doctype html>\n' + document.documentElement.outerHTML)
