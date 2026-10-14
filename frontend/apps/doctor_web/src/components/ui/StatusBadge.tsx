import React from 'react';
import styles from './StatusBadge.module.css';

export type BadgeVariant =
  | 'fresh'
  | 'stale'
  | 'unavailable'
  | 'disconnected'
  | 'open'
  | 'acknowledged'
  | 'resolved'
  | 'normal_like'
  | 'anomalous'
  | 'insufficient_data'
  | 'critical'
  | 'elevated'
  | 'advisory'
  | 'info';

interface StatusBadgeProps {
  variant: BadgeVariant;
  /** Explicit custom label if different from default */
  label?: string;
  className?: string;
}

const DEFAULT_LABELS: Record<BadgeVariant, string> = {
  fresh: 'Fresh / Live',
  stale: 'Stale (>60s)',
  unavailable: 'Unavailable',
  disconnected: 'Disconnected',
  open: 'Open Alert',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
  normal_like: 'Normal-like',
  anomalous: 'Anomalous',
  insufficient_data: 'Insufficient Data',
  critical: 'Critical Alert',
  elevated: 'Elevated Risk',
  advisory: 'Advisory Note',
  info: 'Informational',
};

/**
 * Reusable, high-contrast rectangular status badge.
 * Uses text labels in addition to color indicator for clinical accessibility.
 */
export const StatusBadge: React.FC<StatusBadgeProps> = ({
  variant,
  label,
  className,
}) => {
  const displayLabel = label ?? DEFAULT_LABELS[variant] ?? variant;
  const badgeClass = `${styles.badge} ${styles[variant] ?? ''} ${className ?? ''}`.trim();

  return (
    <span className={badgeClass} role="status">
      <span className={styles.indicator} aria-hidden="true" />
      <span>{displayLabel}</span>
    </span>
  );
};
