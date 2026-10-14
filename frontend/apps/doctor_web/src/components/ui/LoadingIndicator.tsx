import React from 'react';
import styles from './Feedback.module.css';

interface LoadingIndicatorProps {
  label?: string;
  className?: string;
}

export const LoadingIndicator: React.FC<LoadingIndicatorProps> = ({
  label = 'Retrieving clinical records…',
  className,
}) => {
  return (
    <div
      className={`${styles.spinnerWrapper} ${className ?? ''}`}
      role="status"
      aria-live="polite"
    >
      <div className={styles.spinner} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
};
