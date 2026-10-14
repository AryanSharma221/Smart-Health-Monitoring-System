/**
 * SMART HEALTH MONITORING SYSTEM — DOCTOR-PATIENT MESSAGING WORKBENCH
 * 
 * Responsibilities:
 * - Direct clinical communication with authorized assigned patients.
 * - Enforces conversation membership based on doctor-patient assignments.
 * - Real-time thread view with clear distinction between Doctor and Patient messages.
 * - Compliant with agreed endpoints: GET /api/v1/messages?patient_id={id} and POST /api/v1/messages.
 * - Full offline resilience with isolated development fixtures (Kaggle cohort P101–P105).
 * - SIMULATED DATA — NOT FOR MEDICAL USE.
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { useAuth, useDevMode } from '../hooks';
import {
  getAssignedPatients,
  getMessages,
  postMessage,
  KAGGLE_COHORT_FIXTURES,
} from '../api';
import type {
  PatientProfile,
  ClinicalMessage,
} from '../types';
import { formatTimestamp } from '../utils';
import {
  SimulatedDataBanner,
  Button,
  LoadingIndicator,
  InlineError,
  EmptyState,
  SearchIcon,
  RefreshIcon,
  SendIcon,
} from '../components/ui';
import styles from './MessagesPage.module.css';

export const MessagesPage: React.FC = () => {
  const { currentUser } = useAuth();
  const currentUserId = currentUser?.userId;
  const [searchParams, setSearchParams] = useSearchParams();
  const { isFixtureMode, toggleFixtureMode } = useDevMode();

  // Primary State
  const [patients, setPatients] = useState<PatientProfile[]>([]);
  const [patientsLoading, setPatientsLoading] = useState<boolean>(true);
  const [pageError, setPageError] = useState<string | null>(null);

  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(
    searchParams.get('patientId') || null
  );

  const [messages, setMessages] = useState<ClinicalMessage[]>([]);
  const [threadLoading, setThreadLoading] = useState<boolean>(false);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  // Search filter for assigned patients list
  const [patientSearch, setPatientSearch] = useState<string>('');

  // Composer State
  const [draftMessage, setDraftMessage] = useState<string>('');
  const [sending, setSending] = useState<boolean>(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sendSuccess, setSendSuccess] = useState<string | null>(null);

  // Mobile View Switch ('list' or 'thread')
  const [mobileView, setMobileView] = useState<'list' | 'thread'>(
    searchParams.get('patientId') ? 'thread' : 'list'
  );

  // Scroll to bottom ref
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  // Load Assigned Patients
  const loadPatients = useCallback(async (useFixtures: boolean) => {
    setPageError(null);
    if (useFixtures) {
      const fixturePatients = KAGGLE_COHORT_FIXTURES.map((f) => f.patient);
      setPatients(fixturePatients);
      return fixturePatients;
    }

    try {
      const list = await getAssignedPatients();
      setPatients(list);
      return list;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to query assigned patients.';
      setPageError(msg);
      setPatients([]);
      throw err;
    }
  }, []);

  // Load Conversation Messages for Target Patient
  const loadConversation = useCallback(
    async (pid: string, useFixtures: boolean) => {
      setThreadLoading(true);
      setThreadError(null);
      try {
        const thread = await getMessages({
          patientId: pid,
          useFixtures,
          currentUserId,
        });
        setMessages(thread);
        setLastRefreshed(new Date().toISOString());
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to retrieve messages.';
        setThreadError(msg);
        setMessages([]);
      } finally {
        setThreadLoading(false);
      }
    },
    [currentUserId]
  );

  // Initial Mount Effect
  useEffect(() => {
    let isCancelled = false;

    async function init() {
      setPatientsLoading(true);
      try {
        const patientList = await loadPatients(isFixtureMode);
        if (!isCancelled && patientList.length > 0) {
          // If no patient was selected via URL, default to first patient
          const currentUrlPid = searchParams.get('patientId');
          const defaultPid = currentUrlPid || patientList[0].patientId;
          setSelectedPatientId(defaultPid);
          await loadConversation(defaultPid, isFixtureMode);
        }
      } catch {
        // Error state handled in loadPatients
      } finally {
        if (!isCancelled) {
          setPatientsLoading(false);
        }
      }
    }

    init();

    return () => {
      isCancelled = true;
    };
  }, [loadPatients, loadConversation, isFixtureMode, searchParams]);

  // Scroll to bottom when messages update
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Handle Switching Patient
  const handleSelectPatient = (pid: string) => {
    if (pid === selectedPatientId && messages.length > 0) {
      setMobileView('thread');
      return;
    }

    setSelectedPatientId(pid);
    setMobileView('thread');
    setSendError(null);
    setSendSuccess(null);
    setSearchParams({ patientId: pid }, { replace: true });
    loadConversation(pid, isFixtureMode);
  };

  // Manual Refresh
  const handleManualRefresh = async () => {
    setRefreshing(true);
    setSendError(null);
    setSendSuccess(null);
    try {
      await loadPatients(isFixtureMode);
      if (selectedPatientId) {
        await loadConversation(selectedPatientId, isFixtureMode);
      }
    } catch {
      // Handled
    } finally {
      setRefreshing(false);
    }
  };

  // Toggle Development Fixtures
  const handleToggleFixtureMode = () => {
    toggleFixtureMode();
    setPatientsLoading(true);
    setPageError(null);
    setSendError(null);
    setSendSuccess(null);
  };

  // Send Message Submission
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!draftMessage.trim() || !selectedPatientId || sending) return;
    if (draftMessage.length > 1000) {
      setSendError('Message exceeds maximum limit of 1,000 characters.');
      return;
    }

    setSending(true);
    setSendError(null);
    setSendSuccess(null);

    const messageToSend = draftMessage.trim();

    try {
      const created = await postMessage(
        {
          receiverId: selectedPatientId,
          content: messageToSend,
        },
        {
          useFixtures: isFixtureMode,
          currentUserId: currentUser?.userId,
        }
      );

      // Append sent message to active conversation
      setMessages((prev) => [...prev, created]);
      setDraftMessage('');
      setSendSuccess(
        isFixtureMode
          ? '[SIMULATED PREVIEW] Message rendered locally in preview (Backend not connected — message was not transmitted to patient).'
          : 'Message transmitted and persisted.'
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to send message.';
      setSendError(msg);
      // Preserves draftMessage so clinician does not lose content
    } finally {
      setSending(false);
    }
  };

  // Filtered Patients for Left Pane
  const filteredPatients = useMemo(() => {
    if (!patientSearch.trim()) return patients;
    const q = patientSearch.toLowerCase().trim();
    return patients.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.patientId.toLowerCase().includes(q) ||
        (p.sourcePatientId && p.sourcePatientId.toLowerCase().includes(q))
    );
  }, [patients, patientSearch]);

  // Selected Patient Profile
  const selectedPatient = useMemo(() => {
    return patients.find((p) => p.patientId === selectedPatientId) || null;
  }, [patients, selectedPatientId]);

  return (
    <div className={styles.container}>
      {/* 1. Persistent Safety Warning */}
      <SimulatedDataBanner detail="Authorization boundary: Clinical consultations are restricted to verified doctor-patient assignments." />

      {/* Fixture Mode Banner if active */}
      {isFixtureMode && (
        <div className={styles.fixtureNotice} role="alert">
          <div className={styles.fixtureText}>
            <span className={styles.fixtureTag}>Dev Fixture</span>
            <span>
              <strong>Development Fixture Mode Active:</strong> Viewing isolated Kaggle P101–P105 demonstration consultations. FastAPI service is offline.
            </span>
          </div>
          <Button variant="secondary" size="sm" onClick={handleToggleFixtureMode}>
            Switch to Live Gateway Mode
          </Button>
        </div>
      )}

      {/* 2. Page Header */}
      <header className={styles.headerSection}>
        <div className={styles.headerTopRow}>
          <div className={styles.headerTitleCol}>
            <h1 className={styles.title}>Messages</h1>
            <p className={styles.subtitle}>
              Secure consultation messaging with assigned patients under clinical surveillance.
            </p>
          </div>

          <div className={styles.headerActions}>
            <div className={styles.refreshMeta}>
              <span className={styles.lastRefreshedLabel}>Last Successful Refresh</span>
              <span className={styles.lastRefreshedValue}>
                {lastRefreshed ? formatTimestamp(lastRefreshed) : 'Not refreshed'}
              </span>
            </div>

            <Button
              variant="secondary"
              size="sm"
              onClick={handleManualRefresh}
              disabled={patientsLoading || refreshing}
              className={styles.refreshBtn}
              aria-label="Refresh messaging consultations"
            >
              <RefreshIcon size={14} className={refreshing ? styles.spinIcon : undefined} />
              <span>{refreshing ? 'Refreshing…' : 'Refresh'}</span>
            </Button>
          </div>
        </div>
      </header>

      {/* Error Banner when patient retrieval fails */}
      {pageError && !isFixtureMode && (
        <InlineError
          title="Consultation Gateway Communication Failure"
          message={pageError}
          onRetry={() => {
            setPatientsLoading(true);
            loadPatients(false)
              .catch(() => {})
              .finally(() => setPatientsLoading(false));
          }}
        />
      )}

      {/* Development Fixture Switch Offer when offline */}
      {pageError && !isFixtureMode && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: 'var(--color-bg-surface)',
            border: '1px dashed var(--color-border-base)',
            borderRadius: 'var(--radius-xs)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '12px',
            color: 'var(--color-text-secondary)',
          }}
        >
          <span>
            FastAPI consultation messaging endpoint is offline. Would you like to inspect isolated Kaggle P101–P105 development fixtures?
          </span>
          <Button variant="secondary" size="sm" onClick={handleToggleFixtureMode}>
            Inspect with Development Fixtures
          </Button>
        </div>
      )}

      {/* 3. Main Two-Pane Consultation Workbench */}
      {patientsLoading ? (
        <div style={{ padding: '64px 0', textAlign: 'center' }}>
          <LoadingIndicator label="Querying authorized patient consultation directory…" />
        </div>
      ) : patients.length === 0 && !pageError ? (
        <div style={{ backgroundColor: 'var(--color-bg-surface)', padding: '32px', borderRadius: 'var(--radius-xs)' }}>
          <EmptyState
            preset="custom"
            title="No Assigned Patients Available"
            description="You currently have no assigned patients in the clinical database to message."
          />
        </div>
      ) : (
        <div className={styles.chatWorkbench}>
          {/* Left Pane: Assigned Patients Directory */}
          <aside
            className={`${styles.leftPane} ${
              mobileView === 'thread' ? styles.hideOnMobile : ''
            }`}
            aria-label="Assigned Patients Directory"
          >
            <div className={styles.searchBoxArea}>
              <div className={styles.searchInputWrapper}>
                <SearchIcon size={14} className={styles.searchIcon} />
                <input
                  type="text"
                  className={styles.patientSearchInput}
                  placeholder="Filter assigned patients…"
                  value={patientSearch}
                  onChange={(e) => setPatientSearch(e.target.value)}
                  aria-label="Filter assigned patients list"
                />
              </div>
            </div>

            <div className={styles.conversationList} role="listbox" aria-label="Patients">
              {filteredPatients.map((patient) => {
                const isSelected = patient.patientId === selectedPatientId;

                return (
                  <div
                    key={patient.patientId}
                    role="option"
                    aria-selected={isSelected}
                    tabIndex={0}
                    className={`${styles.conversationItem} ${
                      isSelected ? styles.conversationItemSelected : ''
                    }`}
                    onClick={() => handleSelectPatient(patient.patientId)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        handleSelectPatient(patient.patientId);
                      }
                    }}
                  >
                    <div className={styles.conversationItemTop}>
                      <span className={styles.patientName}>{patient.name}</span>
                      <span className={styles.monoTag}>{patient.patientId}</span>
                    </div>

                    <div className={styles.snippetRow}>
                      <span className={styles.snippetText}>
                        {patient.gender ? `${patient.gender} · ` : ''}
                        {patient.sourcePatientId ? `Cohort: ${patient.sourcePatientId}` : 'Assigned patient'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </aside>

          {/* Right Pane: Active Consultation Thread & Composer */}
          <section
            className={`${styles.rightPane} ${
              mobileView === 'list' ? styles.hideOnMobile : ''
            }`}
            aria-label="Active Consultation Thread"
          >
            {selectedPatient ? (
              <>
                {/* Thread Header */}
                <div className={styles.threadHeader}>
                  <div className={styles.threadHeaderLeft}>
                    <button
                      type="button"
                      className={styles.mobileBackBtn}
                      onClick={() => setMobileView('list')}
                      aria-label="Return to patient conversations list"
                    >
                      &larr; Patients
                    </button>

                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <h2 className={styles.threadRecipientName}>{selectedPatient.name}</h2>
                        {isFixtureMode && (
                          <span
                            style={{
                              fontSize: '10px',
                              fontWeight: 600,
                              backgroundColor: '#fef3c7',
                              color: '#92400e',
                              border: '1px solid #f59e0b',
                              borderRadius: '3px',
                              padding: '1px 6px',
                            }}
                          >
                            SIMULATED CONVERSATION
                          </span>
                        )}
                      </div>
                      <span className={styles.monoTag}>ID: {selectedPatient.patientId}</span>
                    </div>
                  </div>

                  <div className={styles.threadHeaderActions}>
                    <Link
                      to={`/patients/${encodeURIComponent(selectedPatient.patientId)}`}
                      className={styles.vitalsLink}
                    >
                      View Vitals &amp; Telemetry &rarr;
                    </Link>

                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => loadConversation(selectedPatient.patientId, isFixtureMode)}
                      disabled={threadLoading}
                      title="Refresh messages in this thread"
                    >
                      <RefreshIcon size={12} className={threadLoading ? styles.spinIcon : undefined} />
                    </Button>
                  </div>
                </div>

                {/* Feedback Banners */}
                {sendSuccess && (
                  <div
                    className={`${styles.feedbackBanner} ${styles.feedbackSuccess}`}
                    style={{ margin: '8px 16px 0' }}
                    role="status"
                  >
                    {sendSuccess}
                  </div>
                )}
                {sendError && (
                  <div
                    className={`${styles.feedbackBanner} ${styles.feedbackError}`}
                    style={{ margin: '8px 16px 0' }}
                    role="alert"
                  >
                    {sendError}
                  </div>
                )}

                {/* Thread Error Banner */}
                {threadError && (
                  <div style={{ padding: '16px' }}>
                    <InlineError
                      title="Failed to Load Consultation Messages"
                      message={threadError}
                      onRetry={() => loadConversation(selectedPatient.patientId, isFixtureMode)}
                    />
                  </div>
                )}

                {/* Messages Scroll Area */}
                <div className={styles.messagesScroll}>
                  {threadLoading ? (
                    <div style={{ padding: '48px 0', textAlign: 'center' }}>
                      <LoadingIndicator label={`Retrieving consultation records for ${selectedPatient.name}…`} />
                    </div>
                  ) : messages.length === 0 ? (
                    <div
                      style={{
                        padding: '48px 24px',
                        textAlign: 'center',
                        color: 'var(--color-text-secondary)',
                        fontSize: '13px',
                      }}
                    >
                      <p style={{ fontWeight: 'var(--weight-semibold)', margin: '0 0 6px 0' }}>
                        No Consultation Messages Recorded
                      </p>
                      <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '12px' }}>
                        {isFixtureMode
                          ? `No messages recorded for ${selectedPatient.name}. In Demo Mode, you can compose messages to preview the clinician messaging interface locally.`
                          : `No messages have been exchanged with ${selectedPatient.name} yet. Compose a message below to initiate communication.`}
                      </p>
                    </div>
                  ) : (
                    messages.map((msg) => {
                      const isDoctor = msg.isFromDoctor;

                      return (
                        <div
                          key={msg.messageId}
                          className={`${styles.messageRow} ${
                            isDoctor ? styles.messageRowDoctor : styles.messageRowPatient
                          }`}
                        >
                          <div
                            className={`${styles.messageBubble} ${
                              isDoctor ? styles.doctorBubble : styles.patientBubble
                            }`}
                          >
                            <span className={styles.messageSender}>
                              {isDoctor ? 'Clinician (You)' : selectedPatient.name}
                            </span>

                            <p className={styles.messageContent}>{msg.content}</p>

                            <div className={styles.messageFooter}>
                              <span>{formatTimestamp(msg.createdAt)}</span>
                              {isFixtureMode && (
                                <span style={{ fontSize: '10px', opacity: 0.75 }}>
                                  · Simulated Preview
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* Message Composer */}
                <form className={styles.composerArea} onSubmit={handleSendMessage}>
                  <label htmlFor="consultation-composer" className={styles.composerLabel}>
                    Compose Consultation Message for {selectedPatient.name}
                  </label>

                  <textarea
                    id="consultation-composer"
                    className={styles.composerTextarea}
                    placeholder={`Type message to ${selectedPatient.name}… (e.g., instructions on vital monitoring, medication reminder)`}
                    value={draftMessage}
                    onChange={(e) => setDraftMessage(e.target.value)}
                    disabled={sending}
                    rows={2}
                  />

                  <div className={styles.composerBottomRow}>
                    <span
                      className={`${styles.charCount} ${
                        draftMessage.length > 1000 ? styles.charCountExceeded : ''
                      }`}
                    >
                      {draftMessage.length} / 1,000 characters
                    </span>

                    <Button
                      type="submit"
                      variant="primary"
                      size="sm"
                      disabled={!draftMessage.trim() || draftMessage.length > 1000 || sending}
                      className={styles.sendBtn}
                    >
                      <SendIcon size={14} />
                      <span>{sending ? 'Sending…' : 'Send Message'}</span>
                    </Button>
                  </div>
                </form>
              </>
            ) : (
              <div style={{ padding: '64px 24px', textAlign: 'center' }}>
                <EmptyState
                  preset="custom"
                  title="No Patient Selected"
                  description="Choose an assigned patient from the directory on the left to inspect consultations and compose messages."
                />
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
};
