import React from 'react';
import { AlertTriangleIcon } from './Icons';
import { Button } from './Button';
import styles from './Feedback.module.css';

interface InlineErrorProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}

export const InlineError: React.FC<InlineErrorProps> = ({
  title = 'Service Communication Error',
  message,
  onRetry,
  className,
}) => {
  return (
    <div
      className={`${styles.inlineError} ${className ?? ''}`}
      role="alert"
      aria-live="assertive"
    >
      <div className={styles.errorContent}>
        <span className={styles.errorIcon} aria-hidden="true">
          <AlertTriangleIcon size={18} />
        </span>
        <div>
          <div className={styles.errorTitle}>{title}</div>
          <div className={styles.errorMessage}>{message}</div>
        </div>
      </div>
      {onRetry && (
        <Button
          variant="secondary"
          size="sm"
          onClick={onRetry}
          aria-label="Retry failed operation"
        >
          Retry
        </Button>
      )}
    </div>
  );
};
