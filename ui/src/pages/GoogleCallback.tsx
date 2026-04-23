import { useEffect, useState, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { exchangeGoogleCode } from '../api/auth';

// Must match the redirect URI the Login page sent to Google. Deriving
// from window.location.origin keeps the two in lock-step regardless of
// which port Vite is running on.
const REDIRECT_URI = `${window.location.origin}/auth/google/callback`;

export default function GoogleCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const hasAttempted = useRef(false);

  useEffect(() => {
    if (hasAttempted.current) return;

    const code = searchParams.get('code');
    const errorParam = searchParams.get('error');

    if (errorParam) {
      setError('Google authentication was cancelled or failed.');
      return;
    }

    if (!code) {
      setError('No authorization code received from Google.');
      return;
    }

    hasAttempted.current = true;

    const authenticate = async () => {
      try {
        const response = await exchangeGoogleCode(code, REDIRECT_URI);
        login(response.user, response.tokens);
        navigate('/dashboard');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Authentication failed');
      }
    };

    authenticate();
  }, [searchParams, login, navigate]);

  const Shell = ({ children }: { children: React.ReactNode }) => (
    <div className="min-h-screen bg-[#f5f3fb] relative overflow-hidden flex items-center justify-center p-4">
      <div className="cockpit-grid-light absolute inset-0 opacity-100 pointer-events-none" />
      <div className="agentic-orb absolute -bottom-[320px] -left-[320px] w-[640px] h-[640px] bg-[#8243EA]/20 rounded-full pointer-events-none" />
      <div className="agentic-orb absolute -top-[280px] -right-[280px] w-[560px] h-[560px] bg-[#2563EB]/15 rounded-full pointer-events-none [animation-delay:1.4s]" />
      <div className="max-w-md w-full bg-white border border-[#e3e5ee] rounded-2xl p-8 text-center relative z-10 shadow-[0_24px_60px_rgba(15,16,32,0.08)]">
        {children}
      </div>
    </div>
  );

  if (error) {
    return (
      <Shell>
        <div className="w-16 h-16 bg-red-50 border border-red-300 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
        <p className="text-[10px] uppercase tracking-[0.32em] text-[#7a7d92] font-semibold">Sign in</p>
        <h1 className="text-xl font-semibold text-[#0f1020] mt-2 mb-2">Authentication failed</h1>
        <p className="text-[#5a5c70] mb-6">{error}</p>
        <button
          onClick={() => navigate('/')}
          className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-5 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition"
        >
          Try again
        </button>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="w-16 h-16 bg-[#f5f3fb] border border-[#e3e5ee] rounded-full flex items-center justify-center mx-auto mb-4">
        <svg className="animate-spin h-8 w-8 text-[#8243EA]" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
      </div>
      <p className="text-[10px] uppercase tracking-[0.32em] text-[#5b21b6] font-semibold">Signing in</p>
      <h1 className="text-xl font-semibold text-[#0f1020] mt-2 mb-2">Linking your Google account</h1>
      <p className="text-[#5a5c70]">Hold on while we complete authentication.</p>
    </Shell>
  );
}
