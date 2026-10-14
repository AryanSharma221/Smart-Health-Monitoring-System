import React from 'react';
import { Button } from './Button';
import styles from './Feedback.module.css';

export type EmptyStatePreset =
  | 'no_patients'
  | 'no_alerts'
  | 'no_history'
  | 'failed_request'
  | 'custom';

interface EmptyStateProps {
  preset?: EmptyStatePreset;
  title?: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: React.ReactNode;
}

const PRESET_DEFAULTS: Record<
  EmptyStatePreset,
  { title: string; description: string }
> = {
  no_patients: {
    title: 'No Patients Assigned',
    description:
      'There are currently no patients linked to your clinician profile in MySQL assignments. Patient assignment is managed server-side.',
  },
  no_alerts: {
    title: 'No Active Alerts',
    description:
      'All telemetry parameters are operating within configured baseline windows or previous alerts have been resolved.',
  },
  no_history: {
    title: 'No Historical Records Available',
    description:
      'No telemetry events have been imported or recorded for the selected filter interval.',
  },
  failed_request: {
    title: 'Gateway Query Failed',
    description:
      'Unable to retrieve records from the FastAPI backend service. Ensure the backend gateway is running.',
  },
  custom: {
    title: 'No Data Available',
    description: 'There are no records to display.',
  },
};

export const EmptyState: React.FC<EmptyStateProps> = ({
  preset = 'custom',
  title,
  description,
  actionLabel,
  onAction,
  icon,
}) => {
  const finalTitle = title ?? PRESET_DEFAULTS[preset].title;
  const finalDescription = description ?? PRESET_DEFAULTS[preset].description;

  return (
    <div className={styles.emptyState} role="region" aria-label="Empty State">
      {icon && <div className={styles.emptyIcon}>{icon}</div>}
      <h3 className={styles.emptyTitle}>{finalTitle}</h3>
      <p className={styles.emptyDescription}>{finalDescription}</p>
      {onAction && actionLabel && (
        <div className={styles.emptyAction}>
          <Button variant="secondary" size="sm" onClick={onAction}>
            {actionLabel}
          </Button>
        </div>
      )}
    </div>
  );
};
