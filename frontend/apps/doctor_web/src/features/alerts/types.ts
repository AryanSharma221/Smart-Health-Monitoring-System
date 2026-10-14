import type { AlertSeverity, AlertStatus } from '../../types';

export interface AlertFilter {
  severity?: AlertSeverity;
  status?: AlertStatus;
  patientId?: string;
}

export interface AcknowledgeAlertPayload {
  alertId: string;
  note: string;
}
