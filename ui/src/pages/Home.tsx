import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Home() {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();

  if (isAuthenticated) {
    navigate('/dashboard');
    return null;
  }

  return (
    <div className="min-h-screen bg-[#f5f3fb] relative overflow-hidden">
      {/* Light grid + lavender orbs */}
      <div className="cockpit-grid-light absolute inset-0 opacity-100 pointer-events-none" />
      <div className="agentic-orb absolute -bottom-[400px] -left-[400px] w-[800px] h-[800px] bg-[#8243EA]/20 rounded-full pointer-events-none" />
      <div className="agentic-orb absolute bottom-[200px] left-[200px] w-[600px] h-[600px] bg-[#2563EB]/15 rounded-full pointer-events-none [animation-delay:1.4s]" />

      <div className="relative z-10 min-h-screen flex flex-col">
        <header className="px-8 py-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] flex items-center justify-center text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]">
              <svg className="w-5 h-5 bulb-glow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 18h6" />
                <path d="M10 22h4" />
                <path d="M12 2a6 6 0 00-4 10.5V15h8v-2.5A6 6 0 0012 2z" />
                <path d="M12 6v3" opacity="0.8" />
              </svg>
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-[0.32em] text-[#7a7d92] font-semibold">Hackathon 2026</p>
              <p className="text-base font-semibold text-[#0f1020] leading-tight">Rosetta</p>
            </div>
          </div>

          <Link
            to="/login"
            className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition"
          >
            Login
          </Link>
        </header>

        <main className="flex-1 px-4 md:px-8 pb-8">
          <div className="max-w-7xl mx-auto">
            <section className="pt-6 md:pt-10">
              <div className="max-w-4xl">
                <p className="inline-flex items-center gap-2 text-[10px] tracking-[0.32em] uppercase text-[#5b21b6] bg-white border border-[#e3e5ee] rounded-full px-3 py-1 mb-4 font-semibold shadow-[0_4px_14px_rgba(130,67,234,0.08)]">
                  Reasoning layer for structured data
                </p>
                <h1 className="text-[#0f1020] text-4xl md:text-6xl font-semibold mb-6 leading-tight">
                  Spreadsheets that
                  <br />
                  <span className="text-[#5b21b6]">explain themselves.</span>
                </h1>
                <p className="text-[#5a5c70] text-lg md:text-xl leading-relaxed max-w-3xl">
                  Rosetta loads workbooks as a semantic graph of cells, formulas, and named ranges. Ask in plain English; get answers backed by executed code, source rows, and a validator trace — inline.
                </p>
              </div>

              <div id="features" className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-4">
                <article className="bg-white border border-[#e3e5ee] rounded-2xl p-5 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
                  <div className="w-12 h-12 rounded-xl bg-[#f5f3fb] border border-[#e3e5ee] flex items-center justify-center mb-4">
                    <svg className="w-6 h-6 text-[#5b21b6]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V8m5 8V4m5 12v-6M4 20h16" />
                    </svg>
                  </div>
                  <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold">Insight</p>
                  <h3 className="text-[#0f1020] font-semibold mt-1 mb-2">Schema-aware questions</h3>
                  <p className="text-[#5a5c70] text-sm">Ask about line items, named ranges, or pivot summaries. Rosetta reads structure before it reads cells.</p>
                </article>

                <article className="bg-white border border-[#e3e5ee] rounded-2xl p-5 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
                  <div className="w-12 h-12 rounded-xl bg-[#f5f3fb] border border-[#e3e5ee] flex items-center justify-center mb-4">
                    <svg className="w-6 h-6 text-[#5b21b6]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7h16M4 12h16M4 17h10" />
                    </svg>
                  </div>
                  <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold">Execution</p>
                  <h3 className="text-[#0f1020] font-semibold mt-1 mb-2">Backed by code, not vibes</h3>
                  <p className="text-[#5a5c70] text-sm">Every answer ships with the executed pandas snippet and a backward-trace tree from the cited cell.</p>
                </article>

                <article className="bg-white border border-[#e3e5ee] rounded-2xl p-5 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
                  <div className="w-12 h-12 rounded-xl bg-[#f5f3fb] border border-[#e3e5ee] flex items-center justify-center mb-4">
                    <svg className="w-6 h-6 text-[#5b21b6]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3v18h18M7 13l3-3 3 2 4-5" />
                    </svg>
                  </div>
                  <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold">Validator</p>
                  <h3 className="text-[#0f1020] font-semibold mt-1 mb-2">No orphan answers</h3>
                  <p className="text-[#5a5c70] text-sm">A citation auditor blocks numbers, refs, or named ranges that can't be traced back to a source row.</p>
                </article>
              </div>

              <div className="mt-6 bg-white border border-[#e3e5ee] rounded-2xl p-4 md:p-5 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="bg-[#f9f8fd] rounded-xl border border-[#e3e5ee] p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] mb-3 font-semibold">Upload</p>
                    <svg className="w-full h-24" viewBox="0 0 220 90" fill="none">
                      <rect x="8" y="8" width="204" height="74" rx="10" fill="#ffffff" stroke="#e3e5ee" />
                      <rect x="26" y="24" width="70" height="12" rx="6" fill="#8243EA" />
                      <rect x="26" y="44" width="125" height="8" rx="4" fill="#e3e5ee" />
                      <rect x="26" y="58" width="100" height="8" rx="4" fill="#eef0f7" />
                      <path d="M178 61V33m0 0-8 8m8-8 8 8" stroke="#5b21b6" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>

                  <div className="bg-[#f9f8fd] rounded-xl border border-[#e3e5ee] p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] mb-3 font-semibold">Reason</p>
                    <svg className="w-full h-24" viewBox="0 0 220 90" fill="none">
                      <rect x="8" y="8" width="204" height="74" rx="10" fill="#ffffff" stroke="#e3e5ee" />
                      <circle cx="55" cy="46" r="20" fill="#8243EA22" stroke="#8243EA" />
                      <path d="M55 34v12l9 6" stroke="#5b21b6" strokeWidth="3" strokeLinecap="round" />
                      <rect x="95" y="30" width="95" height="8" rx="4" fill="#e3e5ee" />
                      <rect x="95" y="46" width="70" height="8" rx="4" fill="#eef0f7" />
                      <rect x="95" y="62" width="82" height="8" rx="4" fill="#8243EA" />
                    </svg>
                  </div>

                  <div className="bg-[#f9f8fd] rounded-xl border border-[#e3e5ee] p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] mb-3 font-semibold">Trace</p>
                    <svg className="w-full h-24" viewBox="0 0 220 90" fill="none">
                      <rect x="8" y="8" width="204" height="74" rx="10" fill="#ffffff" stroke="#e3e5ee" />
                      <rect x="30" y="52" width="16" height="20" rx="4" fill="#8243EA" />
                      <rect x="54" y="42" width="16" height="30" rx="4" fill="#5b21b6" />
                      <rect x="78" y="32" width="16" height="40" rx="4" fill="#2563EB" />
                      <path d="M122 63c13-19 24-27 40-20 10 4 16 2 24-7" stroke="#5b21b6" strokeWidth="3" strokeLinecap="round" />
                    </svg>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </main>

        <footer className="px-8 py-6 text-center">
          <p className="text-[10px] uppercase tracking-[0.32em] text-[#7a7d92] font-semibold">Hackathon 2026 · Rosetta · No black boxes</p>
        </footer>
      </div>
    </div>
  );
}
