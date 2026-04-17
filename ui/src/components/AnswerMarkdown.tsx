import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * AnswerMarkdown — renders assistant-generated markdown with a distinct
 * monospace style for inline code (`Sheet!Ref`, `=FORMULA`, `VLOOKUP`,
 * `FloorPlanRate`). Block code (triple-backtick fences) keeps a compact
 * dark panel so embedded formulas remain legible.
 */
export default function AnswerMarkdown({ content }: { content: string }) {
  return (
    <div className="prose prose-invert prose-sm max-w-none text-gray-200 [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const isBlock = className?.includes('language-');
            if (isBlock) {
              return (
                <pre className="mt-2 p-3 bg-[#1a1a2e] rounded-lg text-xs text-gray-300 overflow-x-auto">
                  <code {...props}>{children}</code>
                </pre>
              );
            }
            return (
              <code
                className="font-mono text-[12px] text-indigo-200 bg-slate-800/70 px-1.5 py-0.5 rounded border border-slate-700/50"
                {...props}
              >
                {children}
              </code>
            );
          },
          a({ children, href, ...props }) {
            return (
              <a
                href={href}
                className="text-indigo-300 underline hover:text-indigo-200"
                target="_blank"
                rel="noopener noreferrer"
                {...props}
              >
                {children}
              </a>
            );
          },
          table({ children }) {
            return (
              <div className="overflow-x-auto my-2">
                <table className="border-collapse border border-slate-700 text-xs">{children}</table>
              </div>
            );
          },
          th({ children }) {
            return <th className="border border-slate-700 px-2 py-1 bg-slate-800/60 text-left">{children}</th>;
          },
          td({ children }) {
            return <td className="border border-slate-700 px-2 py-1">{children}</td>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
