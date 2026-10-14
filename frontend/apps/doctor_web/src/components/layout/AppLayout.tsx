import React, { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { SimulatedDataBanner } from '../ui/SimulatedDataBanner';
import styles from './AppLayout.module.css';

export const AppLayout: React.FC = () => {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);

  // Handle escape key to close mobile drawer
  useEffect(() => {
    if (!isMobileNavOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsMobileNavOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isMobileNavOpen]);

  const toggleMobileNav = () => {
    setIsMobileNavOpen((prev) => !prev);
  };

  const closeMobileNav = () => {
    setIsMobileNavOpen(false);
  };

  return (
    <div className={styles.container}>
      {/* Prominent, persistent simulated data disclaimer */}
      <SimulatedDataBanner />

      <div className={styles.body}>
        <Sidebar isOpen={isMobileNavOpen} onClose={closeMobileNav} />

        <div className={styles.mainWrapper}>
          <Header
            onToggleMenu={toggleMobileNav}
            isMenuOpen={isMobileNavOpen}
          />
          <main className={styles.mainContent} role="main" tabIndex={-1}>
            <div className={styles.contentContainer}>
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
};
