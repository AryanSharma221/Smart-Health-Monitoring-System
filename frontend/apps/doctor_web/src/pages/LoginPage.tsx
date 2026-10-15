import React, { useState, useRef } from 'react';
import { useNavigate, useLocation, Navigate } from 'react-router-dom';
import { useAuth, useDevMode } from '../hooks';
import {
  SimulatedDataBanner,
  BrandMark,
  EyeIcon,
  EyeOffIcon,
  InlineError,
} from '../components/ui';
import styles from './LoginPage.module.css';

export const LoginPage: React.FC = () => {
  const { login, loginDemo, isLoading, authError, clearAuthError, isAuthenticated } = useAuth();
  const { isFixtureMode, setFixtureMode } = useDevMode();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [touched, setTouched] = useState<{ email?: boolean; password?: boolean }>({});

  const emailInputRef = useRef<HTMLInputElement>(null);
  const passwordInputRef = useRef<HTMLInputElement>(null);

  // Target route after successful authentication
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/dashboard';

  // If already authenticated, redirect immediately to target route
  if (isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  const validateEmail = (val: string): string | undefined => {
    const trimmed = val.trim();
    if (!trimmed) {
      return 'Clinician email address is required.';
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(trimmed)) {
      return 'Please enter a valid email address (e.g., doctor@hospital.org).';
    }
    return undefined;
  };

  const validatePassword = (val: string): string | undefined => {
    if (!val) {
      return 'Password is required.';
    }
    return undefined;
  };

  const handleEmailChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setEmail(val);
    if (authError) clearAuthError();
    if (touched.email) {
      setFieldErrors((prev) => ({ ...prev, email: validateEmail(val) }));
    }
  };

  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setPassword(val);
    if (authError) clearAuthError();
    if (touched.password) {
      setFieldErrors((prev) => ({ ...prev, password: validatePassword(val) }));
    }
  };

  const handleBlur = (field: 'email' | 'password') => {
    setTouched((prev) => ({ ...prev, [field]: true }));
    if (field === 'email') {
      setFieldErrors((prev) => ({ ...prev, email: validateEmail(email) }));
    } else {
      setFieldErrors((prev) => ({ ...prev, password: validatePassword(password) }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    setTouched({ email: true, password: true });
    const emailErr = validateEmail(email);
    const passwordErr = validatePassword(password);

    if (emailErr || passwordErr) {
      setFieldErrors({ email: emailErr, password: passwordErr });
      if (emailErr) {
        emailInputRef.current?.focus();
      } else {
        passwordInputRef.current?.focus();
      }
      return;
    }

    setFieldErrors({});

    const success = await login({
      email: email.trim(),
      password,
    });

    if (success) {
      setFixtureMode(false);
      navigate(from, { replace: true });
    } else {
      // Clear password field on failed authentication per clinical security guidelines
      setPassword('');
      passwordInputRef.current?.focus();
    }
  };

  return (
    <div className={styles.container}>
      <SimulatedDataBanner detail="Authorization boundary: Connects exclusively to central FastAPI gateway." />

      <main className={styles.mainLayout}>
        <div className={styles.contentWrapper}>
          {/* Primary Authentication Column */}
          <div className={styles.loginCard}>
            <div className={styles.brandHeader}>
              <div className={styles.brandIcon} aria-hidden="true">
                <BrandMark size={22} />
              </div>
              <div className={styles.brandMeta}>
                <span className={styles.brandTitle}>Smart Health Monitoring</span>
                <span className={styles.brandSubtitle}>Clinician Workstation</span>
              </div>
            </div>

            <div className={styles.formIntro}>
              <h1 className={styles.heading}>Sign in</h1>
              <p className={styles.description}>
                Access assigned patients, review continuous telemetry, and triage clinical alerts.
                Intended for authorized clinical and demonstration personnel.
              </p>
            </div>

            {authError && (
              <InlineError
                title="Authentication Failed"
                message={authError}
              />
            )}

            <form onSubmit={handleSubmit} className={styles.form} noValidate>
              <div className={styles.fieldGroup}>
                <div className={styles.labelRow}>
                  <label htmlFor="login-email" className={styles.label}>
                    Clinician Email
                  </label>
                </div>
                <div className={styles.inputWrapper}>
                  <input
                    ref={emailInputRef}
                    id="login-email"
                    type="email"
                    className={`${styles.input} ${fieldErrors.email ? styles.inputError : ''}`}
                    placeholder="doctor@hospital.org"
                    value={email}
                    onChange={handleEmailChange}
                    onBlur={() => handleBlur('email')}
                    disabled={isLoading}
                    autoComplete="username"
                    autoFocus
                    aria-required="true"
                    aria-invalid={Boolean(fieldErrors.email)}
                    aria-describedby={fieldErrors.email ? 'email-error' : undefined}
                  />
                </div>
                {fieldErrors.email && (
                  <span id="email-error" className={styles.fieldError} role="alert">
                    {fieldErrors.email}
                  </span>
                )}
              </div>

              <div className={styles.fieldGroup}>
                <div className={styles.labelRow}>
                  <label htmlFor="login-password" className={styles.label}>
                    Password
                  </label>
                </div>
                <div className={styles.inputWrapper}>
                  <input
                    ref={passwordInputRef}
                    id="login-password"
                    type={showPassword ? 'text' : 'password'}
                    className={`${styles.input} ${styles.inputPassword} ${
                      fieldErrors.password ? styles.inputError : ''
                    }`}
                    placeholder="••••••••••••"
                    value={password}
                    onChange={handlePasswordChange}
                    onBlur={() => handleBlur('password')}
                    disabled={isLoading}
                    autoComplete="current-password"
                    aria-required="true"
                    aria-invalid={Boolean(fieldErrors.password)}
                    aria-describedby={fieldErrors.password ? 'password-error' : undefined}
                  />
                  <button
                    type="button"
                    className={styles.passwordToggleBtn}
                    onClick={() => setShowPassword((prev) => !prev)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    aria-pressed={showPassword}
                    tabIndex={0}
                  >
                    {showPassword ? <EyeOffIcon size={16} /> : <EyeIcon size={16} />}
                  </button>
                </div>
                {fieldErrors.password && (
                  <span id="password-error" className={styles.fieldError} role="alert">
                    {fieldErrors.password}
                  </span>
                )}
              </div>

              {isFixtureMode ? (
                <>
                  <div
                    style={{
                      padding: '12px 14px',
                      backgroundColor: '#fef3c7',
                      border: '1px solid #f59e0b',
                      borderRadius: 'var(--radius-xs)',
                      marginBottom: '14px',
                    }}
                  >
                    <div
                      style={{
                        fontSize: '11px',
                        fontWeight: 700,
                        color: '#92400e',
                        marginBottom: '4px',
                        letterSpacing: '0.04em',
                      }}
                    >
                      DEMO MODE — SIMULATED DATA
                    </div>
                    <p
                      style={{
                        fontSize: '12px',
                        color: '#78350f',
                        margin: '0 0 10px 0',
                        lineHeight: 1.4,
                      }}
                    >
                      Inspect the clinician workstation using isolated Kaggle benchmark cohorts (P101–P105). No backend connection or live network credentials required.
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        loginDemo();
                        navigate(from, { replace: true });
                      }}
                      className={styles.submitBtn}
                      style={{
                        backgroundColor: '#f59e0b',
                        borderColor: '#d97706',
                        color: '#ffffff',
                        fontWeight: 600,
                      }}
                    >
                      Sign In as Dr. Sarah Jenkins (Demo Session)
                    </button>
                  </div>

                  <div style={{ textAlign: 'center', marginTop: '10px' }}>
                    <button
                      type="button"
                      onClick={() => setFixtureMode(false)}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--color-text-secondary)',
                        fontSize: '11px',
                        cursor: 'pointer',
                        textDecoration: 'underline',
                      }}
                    >
                      Switch to Live Gateway Mode (Requires FastAPI)
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <button
                    type="submit"
                    className={styles.submitBtn}
                    disabled={isLoading}
                  >
                    {isLoading ? (
                      <>
                        <span className={styles.submitSpinner} aria-hidden="true" />
                        <span>Signing in to Gateway...</span>
                      </>
                    ) : (
                      <span>Sign in to Live Gateway</span>
                    )}
                  </button>

                  <div style={{ marginTop: '16px', textAlign: 'center' }}>
                    <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginBottom: '6px' }}>
                      — Fast API Gateway Offline? —
                    </div>
                    <button
                      type="button"
                      onClick={() => setFixtureMode(true)}
                      style={{
                        backgroundColor: 'var(--color-bg-surface-subtle)',
                        border: '1px dashed var(--color-border-base)',
                        color: 'var(--color-text-primary)',
                        padding: '8px 12px',
                        borderRadius: 'var(--radius-xs)',
                        fontSize: '12px',
                        cursor: 'pointer',
                        fontWeight: 500,
                        width: '100%',
                      }}
                    >
                      Enable Demo Mode (Simulated Kaggle Records)
                    </button>
                  </div>
                </>
              )}
            </form>

            <p className={styles.assistanceNote}>
              Demonstration workstation mode provides access to isolated Kaggle benchmark cohorts without requiring an active backend gateway.
            </p>
          </div>

          {/* Secondary Clinical Information Panel */}
          <aside className={styles.infoPanel} aria-label="System Demonstration Context">
            <div className={styles.warningBanner} role="note">
              <span className={styles.warningBadge}>SIMULATED DATA — NOT FOR MEDICAL USE</span>
              <span className={styles.warningDetail}>
                All vital signs, alerts, and anomaly scores displayed on this workstation are derived
                from synthetic ambulatory telemetry and Kaggle benchmark datasets.
              </span>
            </div>

            <div className={styles.infoSections}>
              <div className={styles.infoBlock}>
                <span className={styles.infoBlockTitle}>Demonstration System Architecture</span>
                <p className={styles.infoBlockBody}>
                  This workstation interface evaluates continuous telemetry streams across patient
                  cohorts to demonstrate clinical triage, real-time alerting, and multi-tier
                  monitoring.
                </p>
              </div>

              <div className={styles.infoBlock}>
                <span className={styles.infoBlockTitle}>Patient Cohort Reference</span>
                <p className={styles.infoBlockBody}>
                  Historical monitoring cohorts (P101–P105) represent ambulatory patients tracked
                  across 5 vital channels: heart rate, systolic/diastolic blood pressure, pulse
                  oximetry (SpO2), respiratory rate, and body temperature.
                </p>
              </div>

              <div className={styles.infoBlock}>
                <span className={styles.infoBlockTitle}>Anomaly Detection &amp; Triage</span>
                <p className={styles.infoBlockBody}>
                  Telemetry pipelines are designed for statistical threshold rules and future ML anomaly models;
                  current demonstrations use predefined simulated test examples rather than live model predictions.
                </p>
              </div>
            </div>

            <div className={styles.systemBadgeRow}>
              <div className={styles.systemPill}>
                <span className={styles.statusDot} aria-hidden="true" />
                <span>Gateway: FastAPI v1 (localhost:8000)</span>
              </div>
              <div className={styles.systemPill}>
                <span className={styles.statusDot} aria-hidden="true" />
                <span>Auth: Bearer JWT Session</span>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
};
