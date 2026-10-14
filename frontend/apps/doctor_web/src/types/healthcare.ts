/**
 * SMART HEALTH MONITORING SYSTEM — PATIENTS, ALERTS & WORKFLOW CONTRACTS
 */

export interface PatientProfile {
  patientId: string;
  sourcePatientId?: string; // P101–P105 for Kaggle dataset
  name: string;
  dateOfBirth?: string;
  gender?: 'M' | 'F' | 'Other' | 'Unknown';
  heightCm?: number;
  weightKg?: number;
  assignedDoctorId?: string;
}

export type AlertSeverity = 'critical' | 'elevated' | 'advisory' | 'info';

export type AlertStatus = 'open' | 'acknowledged' | 'resolved';

export interface PatientAlert {
  alertId: string;
  patientId: string;
  severity: AlertSeverity;
  reason: string;
  status: AlertStatus;
  createdAt: string;
  acknowledgedBy?: string;
  acknowledgedAt?: string;
  resolvedAt?: string;
  notes?: string;
  assessmentId?: string;
}

export interface UserSession {
  userId: string;
  email: string;
  name: string;
  role: 'doctor' | 'patient' | 'admin';
  licenseNumber?: string;
}

export interface ClinicalMessage {
  messageId: string;
  senderId: string;
  receiverId: string;
  patientId: string;
  content: string;
  createdAt: string;
  readAt?: string | null;
  isFromDoctor: boolean;
}
