import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { refreshAuthTokens, STORAGE_KEY_TOKENS, type Tokens } from '../api/auth';
import {
  ApiError,
  getDataSource,
  getDataSourceAnalysis,
  type DataSource,
  type WorkbookAnalysis,
} from '../api/dataSources';
import Layout from '../components/Layout';

export default function DataSourceDetail() {
  const { id } = useParams<{ id: string }>();
  const { isAuthenticated, isLoading: authLoading, tokens, updateTokens, logout } = useAuth();
  const navigate = useNavigate();

  const [dataSource, setDataSource] = useState<DataSource | null>(null);
  const [analysis, setAnalysis] = useState<WorkbookAnalysis | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const accessToken = tokens?.access_token ?? '';

  const withAuthRetry = async <T,>(requestFn: (token: string) => Promise<T>): Promise<T> => {
    const currentAccessToken = tokens?.access_token;
    if (!currentAccessToken) {
      throw new Error('You must be logged in to continue');
    }

    try {
      return await requestFn(currentAccessToken);
    } catch (error) {
      const status =
        error instanceof ApiError
          ? error.status
          : (typeof error === 'object' && error && 'status' in error ? Number((error as { status: unknown }).status) : 0);
      const isUnauthorized = status === 401;

      let refreshToken: string | undefined = tokens?.refresh_token;
      if (!refreshToken) {
        const storedTokensRaw = localStorage.getItem(STORAGE_KEY_TOKENS);
        if (storedTokensRaw) {
          try {
            const parsed = JSON.parse(storedTokensRaw) as Partial<Tokens>;
            refreshToken = parsed.refresh_token ?? undefined;
          } catch {
            refreshToken = undefined;
          }
        }
      }

      if (!isUnauthorized || !refreshToken) {
        throw error;
      }

      try {
        const refreshed = await refreshAuthTokens(refreshToken);
        const refreshedTokens: Tokens = {
          access_token: refreshed.access_token,
          refresh_token: refreshed.refresh_token,
          token_type: refreshed.token_type,
          expires_in: refreshed.expires_in,
        };
        updateTokens(refreshedTokens);
        return await requestFn(refreshedTokens.access_token);
      } catch {
        logout();
        navigate('/');
        throw new Error('Your session has expired. Please sign in again.');
      }
    }
  };

  useEffect(() => {
    const fetchData = async () => {
      if (!id || !accessToken) return;

      setIsLoading(true);
      setError(null);

      try {
        const [ds, analysisData] = await Promise.all([
          withAuthRetry((token) => getDataSource(token, id)),
          withAuthRetry((token) => getDataSourceAnalysis(token, id)),
        ]);

        setDataSource(ds);
        setAnalysis(analysisData);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load data source');
      } finally {
        setIsLoading(false);
      }
    };

    if (isAuthenticated && accessToken) {
      fetchData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, isAuthenticated, accessToken]);

  if (!authLoading && !isAuthenticated) {
    navigate('/');
    return null;
  }

  if (authLoading || isLoading) {
    return (
      <Layout activeNavItem="my-files" onNavItemClick={(navId) => navigate(`/dashboard/${navId}`)}>
        <div className="h-full flex items-center justify-center bg-[#f5f3fb]">
          <div className="animate-spin h-8 w-8 border-4 border-[#8243EA] border-t-transparent rounded-full" />
        </div>
      </Layout>
    );
  }

  if (error || !dataSource) {
    return (
      <Layout activeNavItem="my-files" onNavItemClick={(navId) => navigate(`/dashboard/${navId}`)}>
        <div className="h-full m-4 flex flex-col">
          <div className="bg-white border border-[#e3e5ee] rounded-2xl p-6 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-red-50 border border-red-300 rounded-xl flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-[#0f1020] mb-2">Could not load source</h3>
              <p className="text-[#7a7d92] text-sm mb-4">{error || 'Data source not found'}</p>
              <button
                onClick={() => navigate('/dashboard/my-files')}
                className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-5 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition"
              >
                Back to sources
              </button>
            </div>
          </div>
        </div>
      </Layout>
    );
  }

  const formatFileSize = (bytes: number): string => {
    const mb = bytes / (1024 * 1024);
    if (mb >= 1) return `${mb.toFixed(2)} MB`;
    const kb = bytes / 1024;
    return `${kb.toFixed(1)} KB`;
  };

  const formatDate = (isoDate: string): string => new Date(isoDate).toLocaleString();

  const SectionLabel = ({ children }: { children: React.ReactNode }) => (
    <p className="text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] font-semibold">{children}</p>
  );

  const StatCell = ({ label, value, tone = 'default' }: { label: string; value: React.ReactNode; tone?: 'default' | 'accent' | 'success' | 'danger' }) => (
    <div className="bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
      <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold">{label}</p>
      <p className={`text-xl font-bold mt-1 ${
        tone === 'accent' ? 'text-[#5b21b6]' :
        tone === 'success' ? 'text-emerald-600' :
        tone === 'danger' ? 'text-red-600' :
        'text-[#0f1020]'
      }`}>
        {value}
      </p>
    </div>
  );

  return (
    <Layout activeNavItem="my-files" onNavItemClick={(navId) => navigate(`/dashboard/${navId}`)}>
      <div className="h-full m-4 flex flex-col gap-4 overflow-auto">
        {/* Back Button & Header */}
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/dashboard/my-files')}
            className="p-2 bg-white border border-[#e3e5ee] rounded-lg text-[#5a5c70] hover:text-[#5b21b6] hover:border-[#8243EA]/40 transition"
            title="Back to sources"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <p className="text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] font-semibold">Source</p>
            <h1 className="text-2xl font-semibold text-[#0f1020]">{dataSource.name}</h1>
            <p className="text-[#7a7d92] text-sm">{dataSource.original_file_name}</p>
          </div>
        </div>

        {/* File Info Card */}
        <div className="bg-white border border-[#e3e5ee] rounded-2xl p-6 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
          <SectionLabel>File information</SectionLabel>
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCell label="File size" value={formatFileSize(dataSource.file_size_bytes)} />
            <StatCell label="Sheets" value={dataSource.sheet_count} />
            <StatCell label="Extension" value={dataSource.file_extension} />
            <StatCell label="Uploaded" value={<span className="text-sm font-semibold">{formatDate(dataSource.created_at)}</span>} />
          </div>
          <div className="mt-4 bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
            <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold mb-2">Sheet names</p>
            <div className="flex flex-wrap gap-2">
              {dataSource.sheet_names.map((name, idx) => (
                <span key={idx} className="px-3 py-1 bg-[#8243EA]/10 text-[#5b21b6] rounded-lg text-sm font-medium">
                  {name}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Analysis Section */}
        {analysis ? (
          <>
            <div className="bg-white border border-[#e3e5ee] rounded-2xl p-6 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
              <SectionLabel>Workbook analysis</SectionLabel>

              {analysis.overall_purpose && (
                <div className="mt-3 mb-4 p-4 bg-[#f9f8fd] rounded-xl border-l-4 border-[#8243EA]">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold mb-1">Purpose</p>
                  <p className="text-[#0f1020] font-medium">{analysis.overall_purpose}</p>
                </div>
              )}

              <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCell label="Total rows" value={analysis.summary?.total_rows?.toLocaleString() ?? '-'} />
                <StatCell label="Total columns" value={analysis.summary?.total_columns?.toLocaleString() ?? '-'} />
                <StatCell label="Formulas" value={analysis.total_formulas.toLocaleString()} tone={analysis.total_formulas > 0 ? 'accent' : 'default'} />
                <StatCell label="Errors" value={analysis.total_errors.toLocaleString()} tone={analysis.total_errors > 0 ? 'danger' : 'success'} />
              </div>

              {analysis.summary?.formula_categories && analysis.summary.formula_categories.length > 0 && (
                <div className="mt-4 bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold mb-2">Formula categories</p>
                  <div className="flex flex-wrap gap-2">
                    {analysis.summary.formula_categories.map((cat, idx) => (
                      <span key={idx} className="px-3 py-1 bg-[#8243EA]/10 text-[#5b21b6] rounded-lg text-sm font-mono">
                        {cat}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {analysis.summary?.error_types && analysis.summary.error_types.length > 0 && (
                <div className="mt-4 bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold mb-2">Error types</p>
                  <div className="flex flex-wrap gap-2">
                    {analysis.summary.error_types.map((errType, idx) => (
                      <span key={idx} className="px-3 py-1 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm font-mono">
                        {errType}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {analysis.summary?.column_purposes && Object.keys(analysis.summary.column_purposes).length > 0 && (
                <div className="mt-4 bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold mb-2">Column types</p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(analysis.summary.column_purposes).map(([purpose, count], idx) => (
                      <span key={idx} className="px-3 py-1 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg text-sm">
                        {purpose}: {count}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Sheet Details */}
            <div className="bg-white border border-[#e3e5ee] rounded-2xl p-6 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
              <SectionLabel>Sheet details · {analysis.sheets.length}</SectionLabel>

              <div className="mt-3 space-y-4">
                {analysis.sheets.map((sheet, idx) => (
                  <div key={idx} className="bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
                    <div className="flex items-start justify-between mb-2 flex-wrap gap-2">
                      <div className="min-w-0">
                        <h3 className="text-[#0f1020] font-semibold text-base">{sheet.name}</h3>
                        {sheet.inferred_purpose && (
                          <p className="text-[#5a5c70] text-sm mt-1">{sheet.inferred_purpose}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-[11px]">
                        <span className="text-[#7a7d92]">
                          <span className="font-mono text-[#0f1020]">{sheet.row_count.toLocaleString()}</span> rows
                        </span>
                        <span className="text-[#7a7d92]">
                          <span className="font-mono text-[#0f1020]">{sheet.column_count}</span> cols
                        </span>
                        {sheet.formula_count > 0 && (
                          <span className="text-[#5b21b6]">
                            <span className="font-mono">{sheet.formula_count}</span> formulas
                          </span>
                        )}
                        {sheet.error_count > 0 && (
                          <span className="text-red-600">
                            <span className="font-mono">{sheet.error_count}</span> errors
                          </span>
                        )}
                      </div>
                    </div>

                    {sheet.data_patterns && sheet.data_patterns.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-[#e3e5ee]">
                        <p className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold mb-2">Patterns</p>
                        <div className="flex flex-wrap gap-2">
                          {sheet.data_patterns.map((pattern, pIdx) => (
                            <span key={pIdx} className="px-2 py-1 bg-white border border-[#e3e5ee] text-[#5a5c70] rounded text-xs">
                              {pattern}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="bg-white border border-[#e3e5ee] rounded-2xl p-6 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
            <div className="text-center py-8">
              <div className="w-16 h-16 bg-amber-50 border border-amber-200 rounded-xl flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-[#0f1020] mb-2">Analysis pending</h3>
              <p className="text-[#7a7d92] text-sm mb-4">
                The workbook analysis is still being processed. This happens automatically in the background.
              </p>
              <button
                onClick={() => window.location.reload()}
                className="rounded-lg border border-[#e3e5ee] bg-white px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
              >
                Refresh
              </button>
            </div>
          </div>
        )}

        {/* Action */}
        <div className="bg-white border border-[#e3e5ee] rounded-2xl p-6 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
          <button
            onClick={() => navigate('/dashboard/ask-ai')}
            className="w-full py-3 rounded-xl bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-white text-[11px] font-semibold uppercase tracking-[0.18em] shadow-[0_8px_24px_rgba(130,67,234,0.28)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition flex items-center justify-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            Ask questions about this workbook
          </button>
        </div>
      </div>
    </Layout>
  );
}
