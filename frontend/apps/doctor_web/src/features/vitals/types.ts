import type { VitalsReading } from '../../types';

export interface PatientVitalsSummary {
  patientId: string;
  readings: Record<string, VitalsReading>;
  lastEventId: string | null;
  lastMeasuredAt: string | null;
}
