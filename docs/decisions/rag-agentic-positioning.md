# RAG Roadmap notes — Agentic RAG định vị (từ Alex Xu ByteByteGo post 20/10)

## Bối cảnh: ta đang ở đâu trên đường phát triển RAG
Đã xong (basics — đúng thứ tự bài học của post):
- Hybrid RRF (rag_lexical_weight + rag_vector_weight)
- Contextual Retrieval (chunk context prefix lúc index) — gold pass 92.6%→100%, MRR +6.6%, failed retrievals 4→0
- Rerank conditional + đánh giá bằng chứng: ADR-0014 GIỮ OFF (không precision lift)
- Eval harness DeepEval: Faithfulness/AnswerRelevancy, A/B 39 cases ×2, report-only gate

## Bài học cốt lõi từ post + comments (áp cho chatbot)
1. "Agentic RAG không sửa retrieval kém — nó chỉ retry cùng index xấu N lần."
   → mọi nỗ lực tiếp tục đầu tư vào retrieval basics (chunk-position audit là mục tiếp theo),
   KHÔNG nhảy sang agent loop vì hype.
2. Mỗi vòng agentic = thêm calls + latency + tiền. Bắt đầu bằng RAG thuần + chunking tốt +
   reranker; chỉ thêm agent loop cho câu hỏi THẬT SỰ cần multi-lookup.
3. Luôn cap số vòng retrieval.

## Khi nào chatbot CẦN agentic RAG (tín hiệu mở tính năng)
- Câu hỏi thật của khách liên tục cần nhiều nguồn (đa lô + bảng giá + chính sách cùng lúc)
- Eval cho thấy các câu trả lời thất bại do THIẾU NGUỒN (không do检索 kém) — tức multi-hop thật

## Thiết kế nếu triển khai (ghi trước, không làm bây giờ)
- Agent Orchestrator: chỉ kích hoạt khi retrieval rỗng/điểm thấp (conditional, không mặc định)
- Evaluator Agent: TÁI DỤNG signal từ eval harness có sẵn (faithfulness/relevance score) — không xây agent mới
- Cap 2-3 vòng (không phải 5 như hình) — mỗi vòng = latency + chi phí
- Vòng 2 = rewrite query HOẶC đổi nguồn (vector→lexical→CRM tool), không lặp lại giống hệt

## Việc có ROI hơn agentic RAG (thứ tự gợi ý)
1. Chunk-position audit (Lost-in-the-Middle — mục dang của pack W1)
2. Chạy eval trên bộ câu hỏi THẬT của khách (không chỉ golden tổng hợp)
3. Rerank re-decision khi có data mới (ADR-0014 review lại mỗi tháng)
