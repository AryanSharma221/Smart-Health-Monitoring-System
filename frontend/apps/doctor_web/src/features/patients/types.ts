export interface PatientFilter {
  searchQuery?: string;
  assignedOnly?: boolean;
  freshnessStatus?: string;
}

export interface PatientListItem {
  patientId: string;
  sourcePatientId?: string;
  name: string;
  lastMeasuredAt: string | null;
  overallFreshness: 'fresh' | 'stale' | 'unavailable' | 'disconnected';
  activeAlertCount: number;
}
