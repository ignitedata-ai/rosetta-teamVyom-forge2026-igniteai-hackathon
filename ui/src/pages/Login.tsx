import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getGoogleAuthUrl } from '../api/auth';

const REDIRECT_URI = 'http://localhost:3003/auth/google/callback';

export default function Login() {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (isAuthenticated) {
    navigate('/dashboard');
    return null;
  }

  const handleGoogleLogin = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const { url } = await getGoogleAuthUrl(REDIRECT_URI);
      window.location.href = url;
    } catch {
      setError('Failed to initiate Google login. Please try again.');
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#f5f3fb] relative overflow-hidden">
      {/* Light grid + lavender orbs */}
      <div className="cockpit-grid-light absolute inset-0 opacity-100 pointer-events-none" />
      <div className="agentic-orb absolute -top-40 -left-40 h-[420px] w-[420px] rounded-full bg-[#8243EA]/15 pointer-events-none" />
      <div className="agentic-orb absolute -bottom-40 -right-40 h-[480px] w-[480px] rounded-full bg-[#2563EB]/12 pointer-events-none [animation-delay:1.4s]" />

      <div className="relative z-10 min-h-screen flex flex-col">
        <header className="px-8 py-6 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] flex items-center justify-center text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]">
              <svg className="w-5 h-5 bulb-glow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 18h6" />
                <path d="M10 22h4" />
                <path d="M12 2a6 6 0 00-4 10.5V15h8v-2.5A6 6 0 0012 2z" />
                <path d="M12 6v3" opacity="0.8" />
              </svg>
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-[0.32em] text-[#7a7d92] font-semibold">Hackathon 2026</p>
              <p className="text-sm font-semibold text-[#0f1020] leading-tight">Rosetta</p>
            </div>
          </Link>

          <Link
            to="/"
            className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
          >
            Back to home
          </Link>
        </header>

        <main className="flex-1 flex items-center justify-center px-4">
          <div className="w-full max-w-md bg-white border border-[#e3e5ee] rounded-2xl p-8 shadow-[0_24px_60px_rgba(15,16,32,0.08)]">
            <div className="text-center mb-6">
              <p className="text-[10px] uppercase tracking-[0.32em] text-[#5b21b6] font-semibold">Sign in</p>
              <h1 className="text-[#0f1020] text-2xl font-semibold mt-2 mb-2">Continue to Rosetta</h1>
              <p className="text-[#7a7d92] text-sm">A reasoning layer for structured data — schema-aware, execution-based, multi-agent, explainable.</p>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-300 rounded-lg text-red-700 text-sm">
                {error}
              </div>
            )}

            <button
              onClick={handleGoogleLogin}
              disabled={isLoading}
              className="w-full flex items-center justify-center gap-3 px-4 py-3 bg-white border border-[#e3e5ee] rounded-xl text-[#0f1020] font-medium hover:border-[#8243EA]/40 hover:shadow-[0_8px_24px_rgba(130,67,234,0.08)] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <svg className="animate-spin h-5 w-5 text-[#8243EA]" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
              ) : (
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                </svg>
              )}
              <span>{isLoading ? 'Signing in…' : 'Continue with Google'}</span>
            </button>
          </div>
        </main>
      </div>
    </div>
  );
}
