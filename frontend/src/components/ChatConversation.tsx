import { useRef, useEffect } from 'react'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from './EmptyState'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

export interface Message { role: 'user' | 'assistant'; content: string; cited?: string[] }

interface ChatConversationProps {
  messages: Message[]
  loading: boolean
  messagesLoading?: boolean
  activeSseEvent: { event: string; slug?: string } | null
  onNavigate: (slug: string) => void
}

function processWikilinks(text: string): string {
  return text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, slug, display) =>
    `[${display ?? slug}](wiki://${slug})`
  )
}

function isExternalHref(href: string): boolean {
  return /^(https?:\/\/|mailto:|tel:)/i.test(href)
}

function hrefToSlug(href: string): string | null {
  if (!href) return null
  if (href.startsWith('wiki://')) return href.slice(7)
  if (href.startsWith('#')) return null
  if (isExternalHref(href)) return null
  return href.replace(/^\.\//, '')
}

function sseStatusLabel(active: { event: string; slug?: string } | null): string {
  if (!active) return 'Thinking…'
  if (active.event === 'agent:reading') return active.slug ? `⟳ Reading ${active.slug}…` : '⟳ Reading…'
  if (active.event === 'agent:writing') return active.slug ? `⟳ Writing ${active.slug}…` : '⟳ Writing…'
  return 'Thinking…'
}

function sseStatusAnimKey(active: { event: string; slug?: string } | null): string {
  if (!active) return 'thinking'
  return active.slug ?? active.event
}

const markdownComponents = (onNavigate: (slug: string) => void) => ({
  a({ href, children }: { href?: string; children?: React.ReactNode }) {
    const slug = href ? hrefToSlug(href) : null
    if (href && slug) {
      return (
        <span
          role="link"
          tabIndex={0}
          onClick={() => onNavigate(slug)}
          onKeyDown={(e) => e.key === 'Enter' && onNavigate(slug)}
          className="cursor-pointer text-primary underline"
        >
          {children}
        </span>
      )
    }
    return <a href={href} target="_blank" rel="noreferrer">{children}</a>
  },
  ul({ children }: { children?: React.ReactNode }) {
    return <ul className="my-1 list-disc pl-5">{children}</ul>
  },
  ol({ children }: { children?: React.ReactNode }) {
    return <ol className="my-1 list-decimal pl-5">{children}</ol>
  },
  p({ children }: { children?: React.ReactNode }) {
    return <p className="my-1">{children}</p>
  },
})

export default function ChatConversation({
  messages,
  loading,
  messagesLoading,
  activeSseEvent,
  onNavigate,
}: ChatConversationProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  return (
    <>
      <style>{`
        @keyframes fadeSlide {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div className="flex flex-col gap-1 py-2">
        {messagesLoading && (
          <div className="space-y-3 px-3 py-4">
            <Skeleton className="ml-auto h-8 w-3/5" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-12 w-4/5" />
          </div>
        )}
        {!messagesLoading && messages.length === 0 && (
          <EmptyState
            title="No messages yet"
            description="Ask anything — the agent will search your wiki."
          />
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="px-3 py-2 text-sm text-foreground">
              {m.content}
            </div>
          ) : (
            <div key={i} className="flex flex-col">
              <Card className="mx-3 my-2 border-border bg-card p-3 text-sm leading-relaxed text-card-foreground">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  urlTransform={(url) => url}
                  components={markdownComponents(onNavigate)}
                >
                  {processWikilinks(m.content)}
                </ReactMarkdown>
              </Card>
              {m.cited && m.cited.length > 0 && (
                <>
                  <p className="mx-3 mt-0.5 px-1 text-xs text-muted-foreground/80">
                    searched {m.cited.length} page{m.cited.length === 1 ? '' : 's'}
                  </p>
                  <p className="mx-3 mt-0.5 px-1 text-xs text-muted-foreground">
                    Sources:{' '}
                    {m.cited.map((slug) => (
                      <span
                        key={slug}
                        onClick={() => onNavigate(slug)}
                        className="mr-1.5 cursor-pointer text-primary underline"
                      >
                        {slug}
                      </span>
                    ))}
                  </p>
                </>
              )}
            </div>
          )
        )}
        {loading && (
          <Card className="mx-3 my-2 border-border bg-muted/50 p-3">
            <div className="mb-2 space-y-1.5">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-4/5" />
              <Skeleton className="h-3 w-2/3" />
            </div>
            <span
              key={sseStatusAnimKey(activeSseEvent)}
              className="inline-block text-sm text-muted-foreground"
              style={{ animation: 'fadeSlide 200ms ease' }}
            >
              {sseStatusLabel(activeSseEvent)}
            </span>
          </Card>
        )}
        <div ref={bottomRef} />
      </div>
    </>
  )
}
