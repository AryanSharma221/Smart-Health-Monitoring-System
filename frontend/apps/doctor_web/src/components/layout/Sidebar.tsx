import React from 'react';
import { NavLink, Link } from 'react-router-dom';
import { useAuth } from '../../hooks';
import {
  BrandMark,
  OverviewIcon,
  PatientsIcon,
  AlertsIcon,
  MessagesIcon,
  SystemStatusIcon,
  SettingsIcon,
  CloseIcon,
  SignOutIcon,
} from '../ui/Icons';
import styles from './Sidebar.module.css';

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

interface NavItemDef {
  path: string;
  label: string;
  icon: React.ReactNode;
}

const PRIMARY_NAV: NavItemDef[] = [
  { path: '/dashboard', label: 'Overview', icon: <OverviewIcon /> },
  { path: '/patients', label: 'Patients', icon: <PatientsIcon /> },
  { path: '/alerts', label: 'Alerts', icon: <AlertsIcon /> },
  { path: '/messages', label: 'Messages', icon: <MessagesIcon /> },
];

const SECONDARY_NAV: NavItemDef[] = [
  { path: '/system-status', label: 'System status', icon: <SystemStatusIcon /> },
  { path: '/settings', label: 'Settings', icon: <SettingsIcon /> },
];

export const Sidebar: React.FC<SidebarProps> = ({ isOpen = false, onClose }) => {
  const { currentUser, logout } = useAuth();

  const handleLinkClick = () => {
    if (onClose) onClose();
  };

  return (
    <>
      {/* Mobile Drawer Backdrop */}
      {isOpen && (
        <div
          className={styles.mobileBackdrop}
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`${styles.sidebar} ${isOpen ? styles.open : ''}`}
        aria-label="Clinical Workstation Navigation"
      >
        {/* Brand Header */}
        <div className={styles.brand}>
          <Link
            to="/dashboard"
            className={styles.brandLink}
            onClick={handleLinkClick}
            aria-label="Smart Health Monitoring Dashboard"
          >
            <span className={styles.brandMark}>
              <BrandMark size={22} />
            </span>
            <div className={styles.brandText}>
              <span className={styles.brandWordmark}>Smart Health Monitoring</span>
              <span className={styles.brandSubtitle}>Clinician Workstation</span>
            </div>
          </Link>

          <button
            type="button"
            className={styles.closeDrawerBtn}
            onClick={onClose}
            aria-label="Close navigation drawer"
          >
            <CloseIcon size={18} />
          </button>
        </div>

        {/* Scrollable Navigation Body */}
        <div className={styles.navScrollArea}>
          {/* Primary Navigation Section */}
          <nav className={styles.navSection} aria-label="Primary Clinical Navigation">
            <div className={styles.sectionHeading}>Clinical Monitoring</div>
            {PRIMARY_NAV.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={handleLinkClick}
                className={({ isActive }) =>
                  isActive
                    ? `${styles.navItem} ${styles.navItemActive}`
                    : styles.navItem
                }
              >
                <span className={styles.navIcon} aria-hidden="true">
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>

          {/* Secondary Navigation Section */}
          <nav className={styles.navSection} aria-label="System and Operational Navigation">
            <div className={styles.sectionHeading}>System &amp; Operations</div>
            {SECONDARY_NAV.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={handleLinkClick}
                className={({ isActive }) =>
                  isActive
                    ? `${styles.navItem} ${styles.navItemActive}`
                    : styles.navItem
                }
              >
                <span className={styles.navIcon} aria-hidden="true">
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        {/* Compact Account Area at Bottom */}
        <div className={styles.accountArea}>
          <div className={styles.accountInfo}>
            <span className={styles.accountName}>
              {currentUser ? currentUser.name : 'Unauthenticated'}
            </span>
            <span className={styles.accountRole}>
              {currentUser
                ? currentUser.licenseNumber
                  ? `License ${currentUser.licenseNumber}`
                  : `${currentUser.role.toUpperCase()} · ${currentUser.userId}`
                : 'Guest Session'}
            </span>
          </div>

          {currentUser && (
            <button
              type="button"
              className={styles.signOutBtn}
              onClick={() => {
                logout();
                if (onClose) onClose();
              }}
              title="Sign out from session"
              aria-label="Sign out"
            >
              <SignOutIcon size={14} />
              <span>Exit</span>
            </button>
          )}
        </div>
      </aside>
    </>
  );
};
