interface NavItem {
  id: string;
  label: string;
  hint: string;
  icon: React.ReactNode;
}

interface SidebarProps {
  activeItem?: string;
  onItemClick?: (id: string) => void;
  onNewChat?: () => void;
}

export default function Sidebar({ activeItem = 'ask-ai', onItemClick, onNewChat }: SidebarProps) {
  const navItems: NavItem[] = [
    {
      id: 'ask-ai',
      label: 'Workspace',
      hint: 'Reasoning canvas',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 6h16M4 12h10M4 18h7" />
        </svg>
      ),
    },
    {
      id: 'my-files',
      label: 'Sources',
      hint: 'Workbooks · CSV · APIs',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
      ),
    },
    {
      id: 'conversations',
      label: 'History',
      hint: 'Sessions · usage',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 8v4l3 2m6-2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
  ];

  const handleClick = (id: string) => onItemClick?.(id);

  return (
    <aside
      className="w-64 h-screen border-r border-[#e3e5ee] flex flex-col"
      style={{ background: 'linear-gradient(180deg, #fdfcff, #f3f1fb)' }}
    >
      {/* Brand block */}
      <div className="px-5 pt-6 pb-5 border-b border-[#e3e5ee]">
        <div className="flex items-center gap-3">
          <div
            className="h-9 w-9 rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] flex items-center justify-center text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]"
            title="Rosetta"
          >
            {/* Glowing bulb icon */}
            <svg className="w-5 h-5 bulb-glow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 18h6" />
              <path d="M10 22h4" />
              <path d="M12 2a6 6 0 00-4 10.5V15h8v-2.5A6 6 0 0012 2z" />
              <path d="M12 6v3" opacity="0.8" />
            </svg>
          </div>
          <div className="min-w-0">
            <p className="text-[9px] uppercase tracking-[0.32em] text-[#7a7d92] font-semibold">Hackathon 2026</p>
            <p className="text-sm font-semibold text-[#0f1020] leading-tight">Rosetta</p>
          </div>
        </div>
      </div>

      {/* New Session button */}
      <div className="px-5 pt-5 pb-3">
        <button
          onClick={() => onNewChat?.()}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_24px_rgba(130,67,234,0.28)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M12 4v16m8-8H4" />
          </svg>
          New session
        </button>
      </div>

      {/* Navigate label */}
      <div className="px-5 pt-4 pb-2">
        <span className="text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] font-semibold">Navigate</span>
      </div>

      {/* Nav items */}
      <nav className="flex-1 px-3 py-1">
        <ul className="space-y-1">
          {navItems.map((item) => {
            const isActive = activeItem === item.id;
            return (
              <li key={item.id}>
                <button
                  onClick={() => handleClick(item.id)}
                  className={`w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left transition ${
                    isActive
                      ? 'bg-[#8243EA]/10 text-[#0f1020]'
                      : 'text-[#5a5c70] hover:bg-black/[0.03] hover:text-[#0f1020]'
                  }`}
                >
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-md border ${
                      isActive
                        ? 'border-[#8243EA]/40 bg-[#8243EA]/15 text-[#5b21b6]'
                        : 'border-[#e3e5ee] bg-white text-[#7a7d92]'
                    }`}
                  >
                    {item.icon}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs uppercase tracking-[0.16em] font-semibold">{item.label}</span>
                    <span className="block text-[11px] text-[#7a7d92]">{item.hint}</span>
                  </span>
                  {isActive && <span className="h-1.5 w-1.5 rounded-full bg-[#8243EA]" />}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Trust principles */}
      <div className="px-5 py-4 border-t border-[#e3e5ee]">
        <div className="rounded-lg border border-[#e3e5ee] bg-white p-3">
          <p className="text-[10px] uppercase tracking-[0.22em] text-[#7a7d92] font-semibold">Trust principles</p>
          <ul className="mt-2 space-y-1 text-[11px] text-[#5a5c70] leading-snug">
            <li>· No black boxes</li>
            <li>· No string arithmetic</li>
            <li>· No orphan answers</li>
          </ul>
        </div>
      </div>
    </aside>
  );
}
