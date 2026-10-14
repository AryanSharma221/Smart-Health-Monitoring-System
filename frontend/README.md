# Smart Health Monitoring System — Clinician Web Workstation

[![React](https://img.shields.io/badge/React-19-blue.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-6.0-blue.svg)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-8.3-646CFF.svg)](https://vitejs.dev/)
[![Status](https://img.shields.io/badge/Status-Demonstration--Ready-green.svg)](#)

A high-fidelity, clinical-grade health monitoring dashboard and workstation designed for authorized medical personnel to triage continuous ambulatory telemetry, review vital sign histories, manage clinical surveillance alerts, and conduct consultations.

> [!WARNING]
> **SIMULATED DATA — NOT FOR MEDICAL USE**  
> All vital signs, physiological feeds, and surveillance alerts displayed in this demonstration system are derived from the Kaggle ambulatory benchmark dataset and synthetic clinical models.

---

## 🚀 Quick Start

### Prerequisites
- **Node.js** v20+ / v22+
- **npm** v10+

### Installation & Launch

```bash
# 1. Install dependencies across workspaces
npm install

# 2. Start the local Vite development server
npm run dev
```

The application will be accessible at `http://localhost:5173`.

---

## 🛠️ Verification & Quality Scripts

All scripts can be executed from the project root or inside `apps/doctor_web`:

```bash
# Type-check TypeScript codebase
npm run typecheck

# Lint with Oxlint (0 warnings, 0 errors)
npm run lint

# Run automated unit and integration tests (20/20 passing)
npm run test

# Build production bundle for deployment
npm run build
```

---

## 📂 Project Architecture

```
C:\DBMS DA PROJECT/
├── apps/
│   └── doctor_web/                    # Clinician React + TypeScript Web Application
│       ├── public/                    # Static assets
│       ├── src/
│       │   ├── api/                   # Centralized API client, services & Kaggle fixtures
│       │   ├── auth/                  # Authentication context & demo session provider
│       │   ├── components/            # UI components (Layout, Badges, Charts, Forms)
│       │   ├── context/               # Application-wide Demo Mode context
│       │   ├── hooks/                 # Custom hooks (useAuth, useDevMode)
│       │   ├── pages/                 # Workstation screens (Overview, Patients, Alerts, Messages, Status)
│       │   ├── styles/                # Clinical design tokens, CSS variables & typography
│       │   ├── types/                 # TypeScript interfaces and DTO definitions
│       │   └── utils/                 # Clinical formatters and freshness calculators
│       ├── tests/                     # Vitest / Node test runner test suites
│       └── vite.config.ts             # Vite build configuration
├── Smart_Health_Kaggle_Dataset_Aligned_Documentation/
│                                      # Complete dataset, schema, and API specifications
├── package.json                       # Root workspace configuration
└── README.md                          # Documentation root
```

---

## 🩺 Workstation Demonstration Highlights

- **Workstation Overview (`/dashboard`):** Real-time KPI summaries, feed freshness tracking (&le;60s threshold), Kaggle cohort patient table, and priority triage alert queue.
- **Assigned Patient Directory (`/patients`):** Search, sort, and filter assigned ambulatory patients (P101–P105) by feed status and open alerts.
- **Patient Vital History & Detail (`/patients/:id`):** Multi-channel continuous telemetry charts (Heart Rate, SpO2, Temperature) spanning 1,500 historical events with custom time-range filters (`24h`, `7d`, `30d`, `all`).
- **Clinical Surveillance & Alerts (`/alerts`):** Severity-stratified alerts with audit timeline drawer, supporting in-memory Acknowledge and Resolve triage actions.
- **Doctor–Patient Messaging (`/messages`):** Real-time consultation workbench with template selector and local preview transmission.
- **Demo Controls & Settings (`/settings`):** Orchestrate clinical anomaly scenarios (`normal`, `single_anomaly`, `combined_anomaly`, `missing_data`, `stale_data`, `recovery`) with an instant **Reset Demonstration Baseline** utility.
- **System Status (`/status`):** Real-time gateway connectivity probes, WebSocket stream diagnostics, and architectural roadmap indicators.

---

## 🔒 Standalone Demonstration Mode

The application includes an integrated **Demo Mode** enabled by default, allowing evaluators to explore all screens and workflows completely offline using isolated Kaggle benchmark cohorts:
- Prominently displays `DEMO MODE — SIMULATED DATA` and `SIMULATED DATA — NOT FOR MEDICAL USE`.
- Dedicated 1-click login as `Dr. Sarah Jenkins` (`MD-94821 [DEMO SESSION]`).
- Clean separation between offline demonstration fixtures and future live FastAPI endpoints (`http://localhost:8000`).
