# Judge audit

Chạy trong `src/`: `python -m lab9.judge --csv data/eval/judge_<tone|helpful>_public.csv --audit 5`
Lớp dương (positive) là `FAIL`: việc của judge là **tìm** reply lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt (exit 0) | **dùng**, chỉ làm metric non-blocking |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không đạt κ và R (exit 1) | **loại**, không dùng làm gate |

Ma trận nhầm lẫn (tp / fp / fn / tn):
- tone: 24 / 4 / 6 / 66. Tỉ lệ FAIL judge quan sát 0.28 → sau Rogan-Gladen 0.30.
- helpful: 9 / 0 / 21 / 70. Tỉ lệ FAIL judge quan sát 0.09 → sau Rogan-Gladen 0.30 (người chấm: 30/100).

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em", thêm "nha" là quá suồng sã với khách khiếu nại. Rubric thêm: *xưng "LogiX" và "anh/chị"; FAIL nếu xưng "em/bạn" hoặc có tiểu từ "nha/nhé"* |
| 2 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ nhìn thấy chữ "Dạ, vui lòng" ở đầu câu. Rubric thêm: *FAIL nếu có câu mệnh lệnh hoặc cấm khách liên hệ, kể cả khi mở đầu lịch sự* |
| 3 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu lời xin lỗi. Rubric ghi rõ: *không bắt buộc xin lỗi; ngắn mà đủ ý vẫn là PASS* |
| 4 | H-051 "…đã refund 90.000đ…" | FAIL | PASS | Người | Quy định CS cho phép từ "refund". Rubric thêm danh sách từ tiếng Anh được phép (refund, ship) |
| 5 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người | Lời hứa không có trong kết quả hệ thống. Đây là lỗi **nội dung** chứ không phải giọng văn; chuyển sang grader code (so reply với ledger, FM-08), không bắt judge tone chấm |
| 6 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** (về kết quả) | Ghi chú CSV cho biết nhãn người sai vì đọc nhầm ticket; cần sửa nhãn. Theo rubric tone thì câu này lịch sự, nên ra PASS là đúng. Nhãn người cũng cần audit |
| 7 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | Người | Rubric thêm: *FAIL nếu tiếng Việt không dấu hoặc dịch máy* |
| 8 | HL-015 "…đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000) | PASS | FAIL | Người | Judge không có quyền đọc ledger nên không thể biết số tiền sai. Lỗi tiền phải do code chấm (`refund_amount_correct` + metric FM-08) |
| 9 | HL-016 / HL-035 / HL-043: reply dài, xin lỗi nhiều lần, số tiền sai | PASS | FAIL | Người | **Thiên lệch độ dài/lịch sự (verbosity bias)**: cả 13/13 reply dài hơn 150 ký tự đều bị người chấm FAIL, nhưng judge cho PASS hết |

## Kết luận
- **tone_ok dùng được**: κ = 0.757 ≥ 0.6, P = 0.857 ≥ 0.8, R = 0.80 ≥ 0.7. Lỗi còn lại chủ yếu là bỏ sót sắc thái xưng hô (6 fn) và phạt nhầm reply ngắn hoặc có từ "refund" (4 fp). Cách sửa là bổ sung các mục rubric ở bảng trên. Vì κ chỉ cao hơn sàn khoảng 0.16, judge này chỉ nên làm metric **non-blocking**.
- **helpful bị loại**: recall chỉ 0.30, tức judge bỏ sót 21/30 reply lỗi. Precision 1.0 không cứu được, vì judge gần như chỉ bắt các lỗi hiển nhiên (lạc đề, giọng cụt). Phân tích 21 ca bỏ sót:
  - **18 ca "sai tiền"**: cả 18 ca có số tiền sai đều bị bỏ sót. Judge chỉ đọc chữ, không đọc ledger, nên về cấu trúc nó không thể chấm đúng tiêu chí này.
  - 3 ca sai xưng hô (ví dụ HL-047 "Ok bạn…").
  - Reply dài và xin lỗi nhiều làm judge chấm PASS bất kể nội dung.
  Nếu dùng judge này làm gate, một bản agent báo sai số tiền nhưng viết lịch sự vẫn được merge. Đó chính là FM-08. Tiền và approval luôn chấm bằng code.
- Rogan-Gladen cho thấy dù judge helpful chỉ báo 9% lỗi, tỉ lệ lỗi thật sau hiệu chỉnh là khoảng 30%. Nhưng phép hiệu chỉnh này dựa trên chính dữ liệu dùng để đo sensitivity, nên chỉ để minh họa, không thay được việc sửa judge.
- Rủi ro còn lại: judge mới chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí). Cần nhãn người mới làm tập held-out thật, và cần audit lại cả nhãn người (xem H-081).
