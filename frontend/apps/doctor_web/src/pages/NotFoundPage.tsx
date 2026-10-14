import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import styles from './PagePlaceholder.module.css';

export const NotFoundPage: React.FC = () => {
  const location = useLocation();

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <h1 className={styles.title}>404 — Clinical Route Not Found</h1>
        <span className={styles.routeBadge}>Invalid: {location.pathname}</span>
      </div>

      <p className={styles.description}>
        The requested navigation path <code>{location.pathname}</code> does not correspond to an active clinical workstation view.
      </p>

      <div className={styles.actionRow}>
        <Link to="/dashboard" className={styles.primaryBtn}>
          Return to Overview (/dashboard)
        </Link>
        <Link to="/login" className={styles.secondaryBtn}>
          Go to Login Portal (/login)
        </Link>
      </div>
    </div>
  );
};
