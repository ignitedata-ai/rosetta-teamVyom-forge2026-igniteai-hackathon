import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * AnswerMarkdown — renders assistant-generated markdown on a light surface.
 * Inline code (`Sheet!Ref`, `=FORMULA`, named ranges) is highlighted in a
 * subtle lavender pill; block code is a soft off-white panel.
 */
export default function AnswerMarkdown({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none text-[#0f1020] [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const isBlock = className?.includes('language-');
            if (isBlock) {
              return (
                <pre className="mt-2 p-3 bg-[#f9f8fd] border border-[#e3e5ee] rounded-lg text-xs text-[#0f1020] overflow-x-auto">
                  <code {...props}>{children}</code>
                </pre>
              );
            }
            return (
              <code
                className="font-mono text-[12px] text-[#5b21b6] bg-[#8243EA]/10 px-1.5 py-0.5 rounded border border-[#8243EA]/20"
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
                className="text-[#5b21b6] underline hover:text-[#8243EA]"
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
                <table className="border-collapse border border-[#e3e5ee] text-xs">{children}</table>
              </div>
            );
          },
          th({ children }) {
            return <th className="border border-[#e3e5ee] px-2 py-1 bg-[#f9f8fd] text-left text-[#0f1020]">{children}</th>;
          },
          td({ children }) {
            return <td className="border border-[#e3e5ee] px-2 py-1 text-[#0f1020]">{children}</td>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
