-- Covering index for the chat-history transcript table.
-- Backs vfic_last_messages() (WHERE session_id = ANY($1), DISTINCT ON ... ORDER BY id DESC)
-- and ConversationShow pagination (ORDER BY id DESC). Previously only the serial PK on id
-- existed -> seq scan on every inbox load. Measured: Seq Scan 18.9ms -> Index Only Scan 1.5ms.
CREATE INDEX IF NOT EXISTS vfic_chat_histories_session_id_idx
  ON public.vfic_chat_histories (session_id, id DESC);
