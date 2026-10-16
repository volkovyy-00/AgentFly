import { memo } from 'react'
import { DECOR, TONES } from './graph/tones'

type View = 'trail' | 'graph'

/** The trail is home: only `?view=graph` selects the lane graph, anything else (including `?view=trail`) is the trail. */
export function viewOf(search: string): View {
  return new URLSearchParams(search).get('view') === 'graph' ? 'graph' : 'trail'
}

/** The address of a view, keeping every other query parameter (mock, len, burst, …). The trail is plain `/`. */
export function viewHref(view: View, search: string): string {
  const params = new URLSearchParams(search)
  if (view === 'graph') params.set('view', 'graph')
  else params.delete('view')
  const query = params.toString()
  return query === '' ? '/' : `/?${query}`
}

const TABS: readonly { view: View; label: string }[] = [
  { view: 'trail', label: 'Live Trail' },
  { view: 'graph', label: 'Graph' },
]

/** The page's view switch, shown in the trail's header and above the lane graph. History and Rules come with V9. */
export const ViewTabs = memo(function ViewTabs({ view }: { view: View }) {
  const search = window.location.search
  return (
    <nav aria-label="Views" className="flex gap-0.5">
      {TABS.map((tab) => (
        <a
          key={tab.view}
          href={viewHref(tab.view, search)}
          aria-current={tab.view === view ? 'page' : undefined}
          className={`whitespace-nowrap rounded-md px-2.5 py-1 text-base outline-offset-2 focus-visible:outline-2 ${DECOR.focusRing.classes} ${
            tab.view === view ? TONES.tabCurrent.classes : TONES.empty.classes
          }`}
        >
          {tab.label}
        </a>
      ))}
    </nav>
  )
})
