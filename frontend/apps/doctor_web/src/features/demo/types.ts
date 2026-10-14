export type SimulatorScenario =
  | 'normal'
  | 'single_anomaly'
  | 'combined_anomaly'
  | 'missing_data'
  | 'stale_data'
  | 'recovery';

export interface SimulatorRunStatus {
  runId: string | null;
  isRunning: boolean;
  activeScenario: SimulatorScenario;
  targetPatientId: string;
  intervalSeconds: number;
  lastEventId: string | null;
  lastEmittedAt: string | null;
  failureCount: number;
}
