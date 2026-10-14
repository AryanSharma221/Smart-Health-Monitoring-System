/**
 * SMART HEALTH MONITORING SYSTEM — WEBSOCKET TELEMETRY CONNECTION SERVICE
 * 
 * Interacts with agreed WebSocket endpoints:
 * - POST /api/v1/ws-ticket (requests short-lived authorization ticket)
 * - WS /ws/v1/updates?ticket={ticket} (establishes bidirectional telemetry update push)
 * 
 * STRICT ARCHITECTURAL CONSTRAINTS:
 * 1. SIMULATED DATA — NOT FOR MEDICAL USE.
 * 2. Never claims "Connected" unless real WebSocket handshake is confirmed.
 * 3. Never leaks tokens or tickets in console logs.
 * 4. Cleans up socket connections to prevent duplicate connections on re-render.
 */

import { API_CONFIG } from './config';
import { apiRequest } from './client';

export type WsConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'not_configured'
  | 'error';

export interface WsEventMessage {
  type: string;
  payload?: unknown;
  timestamp?: string;
  source?: string;
}

export interface WsStatusSnapshot {
  state: WsConnectionState;
  url: string;
  hasTicket: boolean;
  lastConnectedAt: string | null;
  lastDisconnectedAt: string | null;
  lastEventReceivedAt: string | null;
  lastEventType: string | null;
  lastError: string | null;
  reconnectAttempts: number;
}

export type WsStatusListener = (snapshot: WsStatusSnapshot) => void;
export type WsEventListener = (event: WsEventMessage) => void;

class WebSocketManager {
  private socket: WebSocket | null = null;
  private state: WsConnectionState = 'disconnected';
  private ticket: string | null = null;
  private lastConnectedAt: string | null = null;
  private lastDisconnectedAt: string | null = null;
  private lastEventReceivedAt: string | null = null;
  private lastEventType: string | null = null;
  private lastError: string | null = null;
  private reconnectAttempts = 0;
  private statusListeners = new Set<WsStatusListener>();
  private eventListeners = new Set<WsEventListener>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private manualDisconnect = false;

  public getSnapshot(): WsStatusSnapshot {
    return {
      state: this.state,
      url: API_CONFIG.wsUrl ? `${API_CONFIG.wsUrl}/ws/v1/updates` : 'Not configured',
      hasTicket: !!this.ticket,
      lastConnectedAt: this.lastConnectedAt,
      lastDisconnectedAt: this.lastDisconnectedAt,
      lastEventReceivedAt: this.lastEventReceivedAt,
      lastEventType: this.lastEventType,
      lastError: this.lastError,
      reconnectAttempts: this.reconnectAttempts,
    };
  }

  private notifyStatus() {
    const snapshot = this.getSnapshot();
    for (const listener of this.statusListeners) {
      try {
        listener(snapshot);
      } catch {
        // Listener safety
      }
    }
  }

  public subscribeStatus(listener: WsStatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.getSnapshot());
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  public subscribeEvents(listener: WsEventListener): () => void {
    this.eventListeners.add(listener);
    return () => {
      this.eventListeners.delete(listener);
    };
  }

  /**
   * Requests a short-lived WebSocket ticket from the backend gateway.
   * POST /api/v1/ws-ticket
   */
  public async requestTicket(): Promise<string> {
    const data = await apiRequest<{ ticket?: string; token?: string }>('/ws-ticket', {
      method: 'POST',
    });

    const ticket = data.ticket || data.token;
    if (!ticket) {
      throw new Error('FastAPI gateway did not return a valid WebSocket ticket.');
    }

    this.ticket = ticket;
    return ticket;
  }

  /**
   * Establishes real WebSocket connection to /ws/v1/updates?ticket={ticket}.
   */
  public async connect(): Promise<void> {
    if (this.state === 'connected' || this.state === 'connecting') {
      return;
    }

    if (!API_CONFIG.wsUrl) {
      this.state = 'not_configured';
      this.notifyStatus();
      return;
    }

    this.manualDisconnect = false;
    this.state = 'connecting';
    this.lastError = null;
    this.notifyStatus();

    let ticket = this.ticket;
    if (!ticket) {
      try {
        ticket = await this.requestTicket();
      } catch (err: unknown) {
        this.state = 'error';
        this.lastError =
          err instanceof Error
            ? `Ticket request failed: ${err.message}`
            : 'Failed to acquire WebSocket authorization ticket.';
        this.notifyStatus();
        return;
      }
    }

    try {
      const cleanWsUrl = API_CONFIG.wsUrl.replace(/\/+$/, '');
      const fullUrl = `${cleanWsUrl}/ws/v1/updates?ticket=${encodeURIComponent(ticket)}`;

      if (this.socket) {
        this.socket.close();
        this.socket = null;
      }

      const ws = new WebSocket(fullUrl);
      this.socket = ws;

      ws.onopen = () => {
        this.state = 'connected';
        this.lastConnectedAt = new Date().toISOString();
        this.lastError = null;
        this.reconnectAttempts = 0;
        this.notifyStatus();
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          const msg: WsEventMessage = {
            type: parsed.type || parsed.event || 'telemetry_update',
            payload: parsed.data || parsed.payload || parsed,
            timestamp: parsed.timestamp || new Date().toISOString(),
            source: parsed.source || 'ws_gateway',
          };

          this.lastEventReceivedAt = msg.timestamp || new Date().toISOString();
          this.lastEventType = msg.type;
          this.notifyStatus();

          for (const el of this.eventListeners) {
            try {
              el(msg);
            } catch {
              // Safe event listener execution
            }
          }
        } catch {
          // Plaintext keepalive / non-JSON message
          this.lastEventReceivedAt = new Date().toISOString();
          this.lastEventType = 'raw_frame';
          this.notifyStatus();
        }
      };

      ws.onerror = () => {
        this.state = 'error';
        this.lastError = 'WebSocket connection error encountered.';
        this.notifyStatus();
      };

      ws.onclose = () => {
        this.state = 'disconnected';
        this.lastDisconnectedAt = new Date().toISOString();
        this.socket = null;
        this.notifyStatus();

        if (!this.manualDisconnect && this.reconnectAttempts < 3) {
          this.reconnectAttempts += 1;
          this.state = 'reconnecting';
          this.ticket = null; // Invalidate short-lived ticket to acquire fresh ticket on reconnect
          this.notifyStatus();
          this.reconnectTimer = setTimeout(() => {
            void this.connect();
          }, 3000);
        }
      };
    } catch (err: unknown) {
      this.state = 'error';
      this.lastError = err instanceof Error ? err.message : 'Failed to instantiate WebSocket.';
      this.notifyStatus();
    }
  }

  /**
   * Disconnects active WebSocket connection and resets reconnect timers.
   */
  public disconnect(): void {
    this.manualDisconnect = true;
    this.ticket = null;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }

    this.state = 'disconnected';
    this.lastDisconnectedAt = new Date().toISOString();
    this.notifyStatus();
  }

  /**
   * Sends arbitrary payload to active WebSocket stream.
   */
  public send(data: unknown): boolean {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(typeof data === 'string' ? data : JSON.stringify(data));
      return true;
    }
    return false;
  }

  /**
   * Emits patient channel subscription payload.
   */
  public subscribePatient(patientId: string): boolean {
    return this.send({ action: 'subscribe', patient_id: patientId });
  }

  /**
   * Emits patient channel unsubscription payload.
   */
  public unsubscribePatient(patientId: string): boolean {
    return this.send({ action: 'unsubscribe', patient_id: patientId });
  }
}

export const wsManager = new WebSocketManager();
