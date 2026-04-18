import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { refreshAuthTokens, STORAGE_KEY_TOKENS, type Tokens } from '../api/auth';
import {
  ApiError,
  deleteDataSource,
  listDataSources,
  uploadDataSource,
  type DataSource,
} from '../api/dataSources';
import {
  askQuestion,
  deleteConversation,
  getConversation,
  getExcelSchema,
  getSchemaInfo,
  getSuggestedQuestions,
  getUsageSummary,
  listConversations,
  processDataSource,
  type AnalyticsChartData,
  type Conversation,
  type ConversationListItem,
  type ExcelSchemaResponse,
  type SchemaInfoResponse,
  type TraceNode,
  type UsageSummaryResponse,
} from '../api/excelAgent';
import Layout from '../components/Layout';
import FormulaModal from '../components/FormulaModal';
import AnswerMarkdown from '../components/AnswerMarkdown';
import AnalyticsChart from '../components/AnalyticsChart';
import SchemaInspector from '../components/SchemaInspector';

export default function Dashboard() {
  const { isAuthenticated, isLoading, tokens, updateTokens, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [dataSourceTotal, setDataSourceTotal] = useState(0);
  const [isDataSourcesLoading, setIsDataSourcesLoading] = useState(false);
  const [isUploadLoading, setIsUploadLoading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [dataSourceName, setDataSourceName] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);

  // Ask AI state
  const [selectedDataSourceId, setSelectedDataSourceId] = useState<string | null>(null);
  const [schemaInfo, setSchemaInfo] = useState<SchemaInfoResponse | null>(null);
  const [workbookSchema, setWorkbookSchema] = useState<ExcelSchemaResponse | null>(null);
  const [isSchemaOpen, setIsSchemaOpen] = useState(false);
  const [isSchemaLoading, setIsSchemaLoading] = useState(false);
  const [schemaLoadError, setSchemaLoadError] = useState<string | null>(null);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [isAskingQuestion, setIsAskingQuestion] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [chatHistory, setChatHistory] = useState<Array<{
    type: 'user' | 'assistant';
    content: string;
    codeUsed?: string | null;
    executionTime?: number;
    error?: string | null;
    inputTokens?: number | null;
    outputTokens?: number | null;
    costUsd?: number | null;
    trace?: TraceNode | null;
    chartData?: AnalyticsChartData | null;
  }>>([]);
  const [askError, setAskError] = useState<string | null>(null);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  // Index of the chat message whose formula is currently open in the modal.
  // `null` means no modal open. Tracks a single modal at a time — matches
  // the UX pattern of opening one visualisation, reviewing it, closing.
  const [formulaModalIdx, setFormulaModalIdx] = useState<number | null>(null);

  // Conversations state
  const [conversations, setConversations] = useState<ConversationListItem[]>([]);
  const [conversationsTotal, setConversationsTotal] = useState(0);
  const [isConversationsLoading, setIsConversationsLoading] = useState(false);
  const [_selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);
  const [usageSummary, setUsageSummary] = useState<UsageSummaryResponse | null>(null);

  const accessToken = tokens?.access_token ?? '';
  const section = location.pathname.split('/')[2] || 'ask-ai';

  const selectedFileSummary = useMemo(() => {
    if (!selectedFile) return null;
    const sizeMb = (selectedFile.size / (1024 * 1024)).toFixed(2);
    return `${selectedFile.name} (${sizeMb} MB)`;
  }, [selectedFile]);

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

  const fetchDataSources = async () => {
    if (!accessToken) return;

    setIsDataSourcesLoading(true);
    setUploadError(null);
    try {
      const response = await withAuthRetry((token) => listDataSources(token, 0, 50));
      setDataSources(response.items);
      setDataSourceTotal(response.total);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Failed to load data sources');
    } finally {
      setIsDataSourcesLoading(false);
    }
  };

  const handleDeleteDataSource = async (dataSource: DataSource) => {
    if (!accessToken) return;
    const confirmed = window.confirm(
      `Delete "${dataSource.name}"? This removes the file, its knowledge-base chunks, and all conversations that used it. This cannot be undone.`
    );
    if (!confirmed) return;

    setUploadError(null);
    try {
      await withAuthRetry((token) => deleteDataSource(token, dataSource.id));
      // Clear selection if the deleted one was active in Ask AI
      if (selectedDataSourceId === dataSource.id) {
        setSelectedDataSourceId(null);
        setSchemaInfo(null);
        setSuggestedQuestions([]);
      }
      await fetchDataSources();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Failed to delete data source');
    }
  };

  useEffect(() => {
    if ((section === 'my-files' || section === 'ask-ai') && isAuthenticated && accessToken) {
      fetchDataSources();
    }
    if (section === 'conversations' && isAuthenticated && accessToken) {
      fetchConversations();
      fetchUsageSummary();
    }
  }, [section, isAuthenticated, accessToken]);

  const fetchConversations = async () => {
    if (!accessToken) return;

    setIsConversationsLoading(true);
    try {
      const response = await withAuthRetry((token) => listConversations(token, null, 0, 50));
      setConversations(response.items);
      setConversationsTotal(response.total);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    } finally {
      setIsConversationsLoading(false);
    }
  };

  const fetchUsageSummary = async () => {
    if (!accessToken) return;

    try {
      const summary = await withAuthRetry((token) => getUsageSummary(token, 30));
      setUsageSummary(summary);
    } catch (error) {
      console.error('Failed to load usage summary:', error);
    }
  };

  const handleLoadConversation = async (conversationId: string) => {
    if (!accessToken) return;

    try {
      const conversation = await withAuthRetry((token) => getConversation(token, conversationId));
      setSelectedConversation(conversation);

      // Navigate to Ask AI with this conversation
      setSelectedDataSourceId(conversation.data_source_id);
      setCurrentConversationId(conversation.id);

      // Convert messages to chat history
      const history = conversation.messages.map((msg) => ({
        type: msg.role as 'user' | 'assistant',
        content: msg.content,
        codeUsed: msg.code_used,
        executionTime: msg.execution_time_ms ?? undefined,
        error: msg.is_error ? msg.error_message : null,
        inputTokens: msg.input_tokens,
        outputTokens: msg.output_tokens,
        costUsd: msg.cost_usd,
      }));
      setChatHistory(history);

      navigate('/dashboard/ask-ai');
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleDeleteConversation = async (conversationId: string) => {
    if (!accessToken) return;

    try {
      await withAuthRetry((token) => deleteConversation(token, conversationId));
      await fetchConversations();
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  // Fetch schema info when data source is selected
  useEffect(() => {
    const fetchSchemaInfo = async () => {
      if (!selectedDataSourceId || !accessToken) return;

      try {
        const info = await withAuthRetry((token) => getSchemaInfo(token, selectedDataSourceId));
        setSchemaInfo(info);

        // If ready for queries, fetch suggested questions
        if (info.is_ready_for_queries) {
          const suggestions = await withAuthRetry((token) =>
            getSuggestedQuestions(token, selectedDataSourceId)
          );
          setSuggestedQuestions(suggestions.questions);
        }
      } catch (error) {
        // Schema might not exist yet, that's ok
        setSchemaInfo(null);
        setSuggestedQuestions([]);
      }
    };

    fetchSchemaInfo();
  }, [selectedDataSourceId, accessToken]);

  const handleProcessDataSource = async () => {
    if (!selectedDataSourceId || !accessToken) return;

    setIsProcessing(true);
    setAskError(null);

    try {
      const result = await withAuthRetry((token) =>
        processDataSource(token, selectedDataSourceId, false)
      );

      setSchemaInfo({
        data_source_id: result.data_source_id,
        processing_status: result.processing_status,
        is_ready_for_queries: result.is_ready_for_queries,
        workbook_purpose: result.workbook_purpose,
        sheet_count: 0,
        queryable_questions_count: result.queryable_questions.length,
        has_data_quality_notes: result.data_quality_notes.length > 0,
      });

      if (result.is_ready_for_queries) {
        setSuggestedQuestions(result.queryable_questions);
      }
    } catch (error) {
      setAskError(error instanceof Error ? error.message : 'Failed to process data source');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleAskQuestion = async (questionText?: string) => {
    const q = questionText || question;
    if (!q.trim() || !selectedDataSourceId || !accessToken) return;

    setIsAskingQuestion(true);
    setAskError(null);

    // Add user message to chat
    setChatHistory((prev) => [...prev, { type: 'user', content: q }]);
    setQuestion('');

    try {
      const response = await withAuthRetry((token) =>
        askQuestion(token, selectedDataSourceId, q, currentConversationId)
      );

      // Update conversation ID if we got one
      if (response.conversation_id) {
        setCurrentConversationId(response.conversation_id);
      }

      // Add assistant response to chat
      setChatHistory((prev) => [
        ...prev,
        {
          type: 'assistant',
          content: response.success
            ? formatAnswer(response.answer)
            : `Error: ${response.error}`,
          codeUsed: response.code_used,
          executionTime: response.execution_time_ms,
          error: response.error,
          inputTokens: response.input_tokens,
          outputTokens: response.output_tokens,
          costUsd: response.cost_usd,
          trace: response.trace ?? null,
          chartData: response.chart_data ?? null,
        },
      ]);
    } catch (error) {
      setChatHistory((prev) => [
        ...prev,
        {
          type: 'assistant',
          content: `Error: ${error instanceof Error ? error.message : 'Failed to get answer'}`,
          error: error instanceof Error ? error.message : 'Unknown error',
        },
      ]);
    } finally {
      setIsAskingQuestion(false);
    }
  };

  const formatAnswer = (answer: unknown): string => {
    if (answer === null || answer === undefined) return 'No result';
    if (typeof answer === 'string') return answer;
    if (typeof answer === 'number') return answer.toLocaleString();
    if (typeof answer === 'boolean') return answer ? 'Yes' : 'No';
    if (Array.isArray(answer)) {
      if (answer.length === 0) return 'No results found';
      // If it's an array of objects (like DataFrame records), format as table
      if (typeof answer[0] === 'object') {
        return JSON.stringify(answer, null, 2);
      }
      return answer.join(', ');
    }
    if (typeof answer === 'object') {
      return JSON.stringify(answer, null, 2);
    }
    return String(answer);
  };

  useEffect(() => {
    if (isAuthenticated && location.pathname === '/dashboard') {
      navigate('/dashboard/ask-ai', { replace: true });
    }
  }, [isAuthenticated, location.pathname, navigate]);

  const handleUpload = async () => {
    setUploadError(null);
    setUploadSuccess(null);

    if (!accessToken) {
      setUploadError('You must be logged in to upload files');
      return;
    }

    if (!dataSourceName.trim()) {
      setUploadError('Please provide a data source name');
      return;
    }

    if (!selectedFile) {
      setUploadError('Please select an Excel file to upload');
      return;
    }

    setIsUploadLoading(true);
    try {
      const created = await withAuthRetry((token) => uploadDataSource(token, dataSourceName.trim(), selectedFile));
      setUploadSuccess(`Created data source: ${created.name}`);
      setDataSourceName('');
      setSelectedFile(null);
      setIsCreateModalOpen(false);
      await fetchDataSources();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Upload failed');
    } finally {
      setIsUploadLoading(false);
    }
  };

  const formatFileSize = (bytes: number): string => {
    const mb = bytes / (1024 * 1024);
    if (mb >= 1) return `${mb.toFixed(2)} MB`;
    const kb = bytes / 1024;
    return `${kb.toFixed(1)} KB`;
  };

  const formatCreatedAt = (isoDate: string): string => {
    return new Date(isoDate).toLocaleString();
  };

  // Redirect to home if not authenticated
  if (!isLoading && !isAuthenticated) {
    navigate('/');
    return null;
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#f5f3fb] flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-[#8243EA] border-t-transparent rounded-full" />
      </div>
    );
  }

  const handleNavClick = (id: string) => {
    navigate(`/dashboard/${id}`);
  };

  const renderContent = () => {
    switch (section) {
      case 'ask-ai': {
        const selectedSource = dataSources.find((ds) => ds.id === selectedDataSourceId) || null;
        const workbookReady = Boolean(schemaInfo?.is_ready_for_queries);
        const statusLabel = !selectedSource
          ? ''
          : workbookReady
          ? 'Ready'
          : (schemaInfo?.processing_status || 'Pending');
        return (
          <div className="relative flex h-full flex-col">
            {/* Floating purple/blue orbs */}
            <div className="pointer-events-none absolute inset-x-0 top-0 h-64 overflow-hidden">
              <div className="agentic-orb absolute left-[8%] top-10 h-48 w-48 rounded-full bg-[#8243EA]/10" />
              <div className="agentic-orb absolute right-[12%] top-6 h-56 w-56 rounded-full bg-[#2563EB]/8 [animation-delay:1.4s]" />
            </div>

            {/* Hero header */}
            <header className="relative px-6 pt-5 pb-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-baseline gap-3">
                    <h1 className="text-2xl font-semibold leading-tight text-[#0f1020]">Rosetta</h1>
                    <span className="hidden text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] sm:inline">Hackathon 2026</span>
                  </div>
                  <p className="mt-0.5 text-xs text-[#7a7d92]">A reasoning layer for structured data — schema-aware, execution-based, multi-agent, explainable.</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={selectedDataSourceId || ''}
                    onChange={(e) => {
                      setSelectedDataSourceId(e.target.value || null);
                      setChatHistory([]);
                      setSchemaInfo(null);
                      setWorkbookSchema(null);
                      setSchemaLoadError(null);
                      setSuggestedQuestions([]);
                      setCurrentConversationId(null);
                    }}
                    className="min-w-[200px] rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-sm text-[#0f1020] outline-none focus:border-[#8243EA]/50"
                  >
                    <option value="">Select a workbook…</option>
                    {dataSources.map((ds) => (
                      <option key={ds.id} value={ds.id}>{ds.name}</option>
                    ))}
                  </select>

                  {selectedDataSourceId && !workbookReady && (
                    <button
                      onClick={handleProcessDataSource}
                      disabled={isProcessing}
                      className="rounded-lg border border-[#8243EA]/40 bg-[#8243EA]/15 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5b21b6] hover:bg-[#8243EA]/25 disabled:opacity-50"
                    >
                      {isProcessing ? 'Preparing…' : 'Prepare'}
                    </button>
                  )}

                  {selectedDataSourceId && workbookReady && (
                    <button
                      onClick={async () => {
                        setIsSchemaOpen(true);
                        if (!workbookSchema && !isSchemaLoading) {
                          setIsSchemaLoading(true);
                          setSchemaLoadError(null);
                          try {
                            const full = await withAuthRetry((token) =>
                              getExcelSchema(token, selectedDataSourceId)
                            );
                            setWorkbookSchema(full);
                          } catch (err) {
                            setSchemaLoadError(
                              err instanceof Error ? err.message : 'Failed to load schema'
                            );
                          } finally {
                            setIsSchemaLoading(false);
                          }
                        }
                      }}
                      className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
                      title="Inspect workbook schema and table relationships"
                    >
                      Schema
                    </button>
                  )}

                  {chatHistory.length > 0 && (
                    <button
                      onClick={() => {
                        setChatHistory([]);
                        setCurrentConversationId(null);
                      }}
                      className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
                    >
                      New session
                    </button>
                  )}
                </div>
              </div>
            </header>

            {/* Metrics strip */}
            <div className="relative border-y border-[#e3e5ee] bg-white/70 px-6 py-2 backdrop-blur">
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-[#7a7d92]">
                {selectedSource ? (
                  <>
                    <span className="font-semibold uppercase tracking-[0.18em] text-[#0f1020]">{selectedSource.name}</span>
                    <span><span className="font-mono text-[#0f1020]">{selectedSource.sheet_count}</span> sheets</span>
                    <span><span className="font-mono text-[#0f1020]">{schemaInfo?.queryable_questions_count ?? 0}</span> suggestions</span>
                    <span className="ml-auto inline-flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 rounded-full ${workbookReady ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                      <span className={`uppercase tracking-[0.18em] font-semibold ${workbookReady ? 'text-emerald-600' : 'text-amber-600'}`}>{statusLabel}</span>
                    </span>
                  </>
                ) : (
                  <span className="text-[#7a7d92]">No workbook selected</span>
                )}
              </div>
            </div>

            {/* Error banner */}
            {askError && (
              <div className="mx-6 mt-3 rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-700">
                {askError}
              </div>
            )}

            {/* Chat canvas */}
            <div className="relative flex flex-1 min-h-0 flex-col overflow-hidden">
              <div className="flex-1 px-6 py-6 overflow-auto">
                {!selectedDataSourceId ? (
                  // Pre-workbook hero
                  <div className="agentic-slide-up flex flex-col items-center justify-center py-16 text-center">
                    <p className="text-[10px] uppercase tracking-[0.32em] text-[#5b21b6] font-semibold">Ready</p>
                    <h2 className="mt-3 text-3xl font-semibold leading-tight text-[#0f1020]">
                      Ask a question. <span className="text-[#7a7d92]">Get a defensible answer.</span>
                    </h2>
                    <p className="mt-3 max-w-lg text-sm text-[#5a5c70]">
                      Every result comes paired with the executed code, the source rows, and a validator trace — inline.
                    </p>
                    {dataSources.length === 0 && (
                      <button
                        onClick={() => navigate('/dashboard/my-files')}
                        className="mt-6 rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-5 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)]"
                      >
                        Upload a workbook
                      </button>
                    )}
                  </div>
                ) : chatHistory.length === 0 && suggestedQuestions.length > 0 ? (
                  // Suggested questions
                  <div className="agentic-slide-up mx-auto w-full max-w-4xl space-y-4">
                    <p className="text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] font-semibold">Suggested questions</p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {suggestedQuestions.slice(0, 6).map((q, idx) => (
                        <button
                          key={idx}
                          onClick={() => handleAskQuestion(q)}
                          disabled={isAskingQuestion}
                          className="rounded-xl border border-[#e3e5ee] bg-white p-4 text-left text-sm text-[#0f1020] hover:border-[#8243EA]/40 hover:shadow-[0_8px_24px_rgba(130,67,234,0.08)] transition-all disabled:opacity-50"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : chatHistory.length === 0 ? (
                  // Empty state
                  <div className="agentic-slide-up flex flex-col items-center justify-center py-16 text-center">
                    <p className="text-[10px] uppercase tracking-[0.32em] text-[#5b21b6] font-semibold">Ready</p>
                    <h2 className="mt-3 text-2xl font-semibold leading-tight text-[#0f1020]">
                      Ask a question below.
                    </h2>
                    <p className="mt-3 max-w-lg text-sm text-[#5a5c70]">
                      Schema is loaded. Your workbook is queryable.
                    </p>
                  </div>
                ) : (
                  // Chat history
                  <div className="mx-auto w-full max-w-4xl space-y-6">
                    {chatHistory.map((msg, idx) => (
                      <div
                        key={idx}
                        className={`agentic-slide-up flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}
                      >
                        {msg.type === 'user' ? (
                          <div className="max-w-[88%] rounded-2xl rounded-br-md bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-4 py-2.5 text-[15px] leading-6 text-white shadow-[0_8px_24px_rgba(130,67,234,0.18)]">
                            {msg.content}
                          </div>
                        ) : (
                          <div className="flex max-w-[88%] gap-3">
                            <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[10px] font-bold text-white shadow-[0_4px_14px_rgba(130,67,234,0.35)]">
                              DI
                            </span>
                            <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-[#e3e5ee] bg-white px-4 py-3 text-[15px] leading-6 text-[#0f1020] shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
                              {msg.error ? (
                                <p className="text-red-600">{msg.content}</p>
                              ) : (
                                <AnswerMarkdown content={msg.content} />
                              )}

                              {/* Open the formula-visualisation modal when
                                  the coordinator's answer carries a
                                  backward_trace. Modal hosts a Map and
                                  a Formula (signed-chips) view. */}
                              {!msg.error && msg.trace && (
                                <button
                                  type="button"
                                  onClick={() => setFormulaModalIdx(idx)}
                                  className="mt-3 inline-flex items-center gap-2 rounded-lg border border-[#8243EA]/30 bg-[#8243EA]/10 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5b21b6] hover:bg-[#8243EA]/20 hover:border-[#8243EA]/50 transition"
                                >
                                  <svg
                                    width="14"
                                    height="14"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                  >
                                    <circle cx="12" cy="12" r="9" />
                                    <path d="M12 3v9l7 4" />
                                  </svg>
                                  Visualise formula
                                </button>
                              )}

                              {!msg.error && msg.chartData && (
                                <AnalyticsChart chart={msg.chartData} />
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}

                    {isAskingQuestion && (
                      <div className="agentic-slide-up flex justify-start">
                        <div className="flex max-w-[88%] gap-3">
                          <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[10px] font-bold text-white shadow-[0_4px_14px_rgba(130,67,234,0.35)] cockpit-active-pulse">
                            DI
                          </span>
                          <div className="rounded-2xl rounded-tl-md border border-[#e3e5ee] bg-white px-4 py-3 text-sm text-[#5a5c70]">
                            <div className="flex items-center gap-2">
                              <div className="animate-spin h-4 w-4 border-2 border-[#8243EA] border-t-transparent rounded-full" />
                              <span>Reasoning…</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Composer */}
              <div className="border-t border-[#e3e5ee] bg-white/85 px-6 py-3 backdrop-blur">
                <div className="mx-auto w-full max-w-4xl">
                  <div className="rounded-2xl border border-[#e3e5ee] bg-white shadow-[0_4px_18px_rgba(15,16,32,0.04)] focus-within:border-[#8243EA]/40 focus-within:shadow-[0_8px_28px_rgba(130,67,234,0.1)] transition">
                    <textarea
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          handleAskQuestion();
                        }
                      }}
                      placeholder={
                        !selectedDataSourceId
                          ? 'Select a workbook first…'
                          : !workbookReady
                          ? 'Prepare the workbook first…'
                          : 'Ask a question about your data…'
                      }
                      disabled={!selectedDataSourceId || !workbookReady || isAskingQuestion}
                      rows={1}
                      className="block w-full resize-none bg-transparent px-4 pt-3 text-[15px] leading-6 text-[#0f1020] outline-none placeholder:text-[#9a9caf] disabled:opacity-50"
                    />
                    <div className="flex items-center justify-end gap-2 px-3 pb-2.5 pt-1">
                      <button
                        onClick={() => handleAskQuestion()}
                        disabled={!question.trim() || !selectedDataSourceId || !workbookReady || isAskingQuestion}
                        className="rounded-md bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)] disabled:opacity-40"
                      >
                        {isAskingQuestion ? 'Reasoning…' : 'Send'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Schema Inspector Modal */}
            <SchemaInspector
              open={isSchemaOpen}
              onClose={() => setIsSchemaOpen(false)}
              schema={workbookSchema}
              isLoading={isSchemaLoading}
              error={schemaLoadError}
            />
          </div>
        );
      }

      case 'my-files':
        return (
          <div className="h-full m-4 flex flex-col gap-4">
            <div className="bg-white border border-[#e3e5ee] rounded-2xl h-full overflow-hidden flex flex-col shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
              {/* Header */}
              <div className="px-6 py-4 border-b border-[#e3e5ee] flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] font-semibold">Sources</span>
                  <span className="text-sm font-semibold text-[#0f1020]">Workbooks ({dataSourceTotal})</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={fetchDataSources}
                    className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
                  >
                    Refresh
                  </button>
                  <button
                    onClick={() => {
                      setUploadError(null);
                      setUploadSuccess(null);
                      setIsCreateModalOpen(true);
                    }}
                    className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition"
                  >
                    Create source
                  </button>
                </div>
              </div>

              {uploadError && (
                <div className="mx-4 mt-4 p-3 bg-red-50 border border-red-300 rounded-lg text-sm text-red-700">{uploadError}</div>
              )}
              {uploadSuccess && (
                <div className="mx-4 mt-4 p-3 bg-emerald-50 border border-emerald-300 rounded-lg text-sm text-emerald-700">{uploadSuccess}</div>
              )}

              {isDataSourcesLoading ? (
                <div className="flex-1 flex items-center justify-center">
                  <div className="animate-spin h-7 w-7 border-4 border-[#8243EA] border-t-transparent rounded-full" />
                </div>
              ) : dataSources.length === 0 ? (
                <div className="flex-1 flex items-center justify-center">
                  <div className="text-center">
                    <div className="w-20 h-20 bg-[#f5f3fb] border border-[#e3e5ee] rounded-2xl flex items-center justify-center mx-auto mb-4">
                      <svg className="w-10 h-10 text-[#5b21b6]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                      </svg>
                    </div>
                    <h3 className="text-lg font-semibold text-[#0f1020] mb-2">No workbooks yet</h3>
                    <p className="text-[#7a7d92] text-sm">Upload your Excel files to create your first source</p>
                  </div>
                </div>
              ) : (
                <div className="flex-1 overflow-auto p-4">
                  <div className="overflow-x-auto rounded-xl border border-[#e3e5ee]">
                    <table className="w-full min-w-[860px] text-sm">
                      <thead className="bg-[#f9f8fd] text-[#5a5c70]">
                        <tr>
                          <th className="text-left px-4 py-3 font-semibold uppercase tracking-[0.12em] text-[10px]">Name</th>
                          <th className="text-left px-4 py-3 font-semibold uppercase tracking-[0.12em] text-[10px]">File</th>
                          <th className="text-left px-4 py-3 font-semibold uppercase tracking-[0.12em] text-[10px]">Size</th>
                          <th className="text-left px-4 py-3 font-semibold uppercase tracking-[0.12em] text-[10px]">Tabs</th>
                          <th className="text-left px-4 py-3 font-semibold uppercase tracking-[0.12em] text-[10px]">Sheet names</th>
                          <th className="text-left px-4 py-3 font-semibold uppercase tracking-[0.12em] text-[10px]">Created</th>
                          <th className="text-right px-4 py-3 font-semibold uppercase tracking-[0.12em] text-[10px]">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dataSources.map((source) => (
                          <tr
                            key={source.id}
                            onClick={() => navigate(`/data-source/${source.id}`)}
                            className="border-t border-[#e3e5ee] bg-white hover:bg-[#f9f8fd] cursor-pointer transition-colors"
                          >
                            <td className="px-4 py-3 text-[#0f1020] font-semibold">{source.name}</td>
                            <td className="px-4 py-3 text-[#5a5c70]">{source.original_file_name}</td>
                            <td className="px-4 py-3 text-[#5a5c70]">{formatFileSize(source.file_size_bytes)}</td>
                            <td className="px-4 py-3 text-[#5a5c70]">{source.sheet_count}</td>
                            <td className="px-4 py-3 text-[#5a5c70] max-w-[320px] truncate" title={source.sheet_names.join(', ')}>
                              {source.sheet_names.join(', ')}
                            </td>
                            <td className="px-4 py-3 text-[#7a7d92]">{formatCreatedAt(source.created_at)}</td>
                            <td className="px-4 py-3 text-right">
                              <button
                                onClick={(event) => {
                                  event.stopPropagation();
                                  handleDeleteDataSource(source);
                                }}
                                className="px-3 py-1.5 rounded-md bg-red-50 border border-red-200 text-red-700 hover:bg-red-100 text-xs font-semibold uppercase tracking-[0.12em] transition-colors"
                                title="Delete this data source"
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            {isCreateModalOpen && (
              <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
                <div
                  className="w-full max-w-2xl bg-[linear-gradient(180deg,#fdfcff,#f3f1fb)] border border-[#e3e5ee] rounded-2xl shadow-[0_40px_100px_rgba(0,0,0,0.25)]"
                >
                  <div className="px-6 py-4 border-b border-[#e3e5ee] flex items-center justify-between bg-white/85 rounded-t-2xl">
                    <div>
                      <p className="text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] font-semibold">New source</p>
                      <h3 className="text-[#0f1020] font-bold text-base">Create data source</h3>
                    </div>
                    <button
                      onClick={() => setIsCreateModalOpen(false)}
                      className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
                    >
                      Close
                    </button>
                  </div>

                  <div className="p-6 space-y-4">
                    <label className="block">
                      <span className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold">Data source name</span>
                      <input
                        type="text"
                        value={dataSourceName}
                        onChange={(event) => setDataSourceName(event.target.value)}
                        placeholder="Quarterly Sales Workbook"
                        className="mt-2 w-full px-4 py-3 bg-white border border-[#e3e5ee] rounded-xl text-[#0f1020] placeholder-[#9a9caf] focus:outline-none focus:border-[#8243EA]/50"
                      />
                    </label>

                    <label className="block">
                      <span className="text-[10px] uppercase tracking-[0.18em] text-[#7a7d92] font-semibold">Excel file</span>
                      <input
                        type="file"
                        accept=".xlsx,.xls,.xlsm"
                        onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                        className="mt-2 w-full px-4 py-2.5 bg-white border border-[#e3e5ee] rounded-xl text-[#5a5c70] file:mr-4 file:px-3 file:py-1.5 file:rounded-md file:border-0 file:bg-[#8243EA]/15 file:text-[#5b21b6] file:font-semibold file:uppercase file:tracking-[0.12em] file:text-[10px]"
                      />
                      {selectedFileSummary && <p className="text-xs text-[#7a7d92] mt-2">{selectedFileSummary}</p>}
                    </label>

                    <div className="flex justify-end gap-3 pt-2">
                      <button
                        onClick={() => setIsCreateModalOpen(false)}
                        className="rounded-lg border border-[#e3e5ee] bg-white px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleUpload}
                        disabled={isUploadLoading}
                        className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-5 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {isUploadLoading ? 'Uploading…' : 'Create'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        );

      case 'conversations':
        return (
          <div className="h-full m-4 flex flex-col gap-4">
            {/* Usage Summary Card */}
            {usageSummary && (
              <div className="bg-white border border-[#e3e5ee] rounded-2xl p-6 shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
                <p className="text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] font-semibold">Usage</p>
                <h3 className="text-[#0f1020] font-semibold mt-1 mb-4">Last {usageSummary.period_days} days</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
                    <p className="text-[#7a7d92] text-[10px] uppercase tracking-[0.18em] font-semibold">Total calls</p>
                    <p className="text-2xl font-bold text-[#0f1020] mt-1">{usageSummary.total_calls.toLocaleString()}</p>
                  </div>
                  <div className="bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
                    <p className="text-[#7a7d92] text-[10px] uppercase tracking-[0.18em] font-semibold">Input tokens</p>
                    <p className="text-2xl font-bold text-[#0f1020] mt-1">{usageSummary.total_input_tokens.toLocaleString()}</p>
                  </div>
                  <div className="bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
                    <p className="text-[#7a7d92] text-[10px] uppercase tracking-[0.18em] font-semibold">Output tokens</p>
                    <p className="text-2xl font-bold text-[#0f1020] mt-1">{usageSummary.total_output_tokens.toLocaleString()}</p>
                  </div>
                  <div className="bg-[#f9f8fd] border border-[#e3e5ee] rounded-xl p-4">
                    <p className="text-[#7a7d92] text-[10px] uppercase tracking-[0.18em] font-semibold">Total cost</p>
                    <p className="text-2xl font-bold text-emerald-600 mt-1">${usageSummary.total_cost_usd.toFixed(4)}</p>
                  </div>
                </div>
              </div>
            )}

            <div className="bg-white border border-[#e3e5ee] rounded-2xl flex-1 overflow-hidden flex flex-col shadow-[0_4px_18px_rgba(15,16,32,0.04)]">
              {/* Header */}
              <div className="px-6 py-4 border-b border-[#e3e5ee] flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-[10px] uppercase tracking-[0.28em] text-[#7a7d92] font-semibold">History</span>
                  <span className="text-sm font-semibold text-[#0f1020]">Sessions ({conversationsTotal})</span>
                </div>
                <button
                  onClick={fetchConversations}
                  className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
                >
                  Refresh
                </button>
              </div>

              {isConversationsLoading ? (
                <div className="flex-1 flex items-center justify-center">
                  <div className="animate-spin h-7 w-7 border-4 border-[#8243EA] border-t-transparent rounded-full" />
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex-1 flex items-center justify-center">
                  <div className="text-center">
                    <div className="w-20 h-20 bg-[#f5f3fb] border border-[#e3e5ee] rounded-2xl flex items-center justify-center mx-auto mb-4">
                      <svg className="w-10 h-10 text-[#5b21b6]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                      </svg>
                    </div>
                    <h3 className="text-lg font-semibold text-[#0f1020] mb-2">No sessions yet</h3>
                    <p className="text-[#7a7d92] text-sm mb-6">Start a chat to see your history here</p>
                    <button
                      onClick={() => navigate('/dashboard/ask-ai')}
                      className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-5 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition"
                    >
                      Start session
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex-1 overflow-auto p-4">
                  <div className="space-y-3">
                    {conversations.map((conv) => {
                      const dataSource = dataSources.find((ds) => ds.id === conv.data_source_id);
                      return (
                        <div
                          key={conv.id}
                          className="bg-white border border-[#e3e5ee] rounded-xl p-4 hover:border-[#8243EA]/40 hover:shadow-[0_8px_24px_rgba(130,67,234,0.08)] transition-all"
                        >
                          <div className="flex items-start justify-between">
                            <div className="flex-1 min-w-0">
                              <h4 className="text-[#0f1020] font-semibold truncate">{conv.title}</h4>
                              <p className="text-[#5a5c70] text-sm mt-1">
                                {dataSource?.name || 'Unknown data source'}
                              </p>
                              <div className="flex items-center gap-4 mt-2 text-xs text-[#7a7d92]">
                                <span>{conv.message_count} messages</span>
                                <span>${conv.total_cost_usd.toFixed(4)}</span>
                                <span>
                                  {conv.last_message_at
                                    ? new Date(conv.last_message_at).toLocaleString()
                                    : new Date(conv.created_at).toLocaleString()}
                                </span>
                              </div>
                            </div>
                            <div className="flex items-center gap-2 ml-4">
                              <button
                                onClick={() => handleLoadConversation(conv.id)}
                                className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-white shadow-[0_4px_14px_rgba(130,67,234,0.25)] hover:shadow-[0_4px_18px_rgba(130,67,234,0.4)] transition"
                              >
                                Continue
                              </button>
                              <button
                                onClick={() => handleDeleteConversation(conv.id)}
                                className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-red-700 hover:bg-red-100 transition"
                              >
                                Delete
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  const handleNewChat = () => {
    // Reset the active chat so the user lands on a fresh Ask AI canvas.
    setChatHistory([]);
    setCurrentConversationId(null);
    setAskError(null);
    setQuestion('');
    if (section !== 'ask-ai') {
      navigate('/dashboard/ask-ai');
    }
  };

  // The formula-visualisation modal lives at the Dashboard root (rather
  // than inline in each message) because only one can be open at a time
  // and we want a single React portal instance owning body scroll lock
  // and backdrop.
  const modalTrace =
    formulaModalIdx != null ? chatHistory[formulaModalIdx]?.trace ?? null : null;

  return (
    <Layout activeNavItem={section} onNavItemClick={handleNavClick} onNewChat={handleNewChat}>
      {renderContent()}
      {modalTrace && (
        <FormulaModal
          trace={modalTrace}
          open={formulaModalIdx != null}
          onClose={() => setFormulaModalIdx(null)}
        />
      )}
    </Layout>
  );
}
