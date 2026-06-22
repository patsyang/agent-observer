import type { LinkedConversation } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { formatDateTime } from './dashboardLabels';

interface Props {
  conversations: LinkedConversation[];
  onOpen: (conversation: LinkedConversation) => void;
}

export function SignalLinkedConversations({ conversations, onOpen }: Props) {
  return (
    <section aria-label="命中会话">
      <div className="section-title-row">
        <h3>命中会话</h3>
        <span>{formatNumber(conversations.length)} 个会话</span>
      </div>
      {conversations.length === 0 ? (
        <p>暂无可定位会话。</p>
      ) : (
        <div className="signal-conversation-grid">
          {conversations.map((conversation) => (
            <button
              className="signal-conversation-card"
              key={conversation.conversation_ref}
              onClick={() => onOpen(conversation)}
              type="button"
            >
              <strong>{conversationName(conversation)}</strong>
              <span>{conversation.workspace?.workspace_label || '工作区未知'}</span>
              <small>
                {formatNumber(conversation.hit_count)} 条命中 / {formatDateTime(conversation.last_seen_at)}
              </small>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function conversationName(conversation: LinkedConversation): string {
  return conversation.session_title || conversation.session_ref || conversation.conversation_ref;
}
