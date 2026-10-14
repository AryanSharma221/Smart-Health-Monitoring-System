export interface MessageItem {
  messageId: string;
  senderId: string;
  senderName: string;
  receiverId: string;
  content: string;
  createdAt: string;
  readAt?: string;
}

export interface SendMessagePayload {
  receiverId: string;
  content: string;
}
