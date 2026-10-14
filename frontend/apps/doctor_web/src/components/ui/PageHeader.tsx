import React from 'react';
import styles from './Heading.module.css';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  breadcrumb?: string;
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  breadcrumb,
  actions,
}) => {
  return (
    <header className={styles.pageHeader}>
      <div className={styles.textGroup}>
        {breadcrumb && <div className={styles.breadcrumbs}>{breadcrumb}</div>}
        <h1 className={styles.pageTitle}>{title}</h1>
        {subtitle && <p className={styles.pageSubtitle}>{subtitle}</p>}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </header>
  );
};
