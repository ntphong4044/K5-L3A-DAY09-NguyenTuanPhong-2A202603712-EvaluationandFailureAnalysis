# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-014@11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, run ID `R-seeded_regression-C-014-s11` |
| Triệu chứng | Grader Lab 8 FAIL (`proposal_mismatch`); `refund_amount_correct` FAIL (ledger 90.000 ≠ label 120.000); `reply_matches_ledger` FAIL (reply "đã hoàn 120.000đ", ledger chỉ 90.000) |
| Bước sai đầu tiên | Event 5 `proposal {"amount_vnd": 120000}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` và event 2 `investigator` đọc đúng đơn O-515. Event 3 `quote 150000` đúng (DMG-04 lớn hơn SHIP-LATE-03, lấy max). Event 4 `refund_history 30000` đúng, vì đơn đã được hoàn 30.000 tiền ship. Đến event 5, agent tự trừ 150.000 − 30.000 rồi mới gọi host, trong khi luật yêu cầu truyền **quote đầy đủ**. Host trừ thêm 30.000 lần nữa nên ledger chỉ còn 90.000 |
| Failure mode | FM-05 pre_deducted (kéo theo FM-08: reply nói 120.000, khác ledger) |
| Đối chứng | `fixed C-014@11`: không có event `refund_history` hay `proposal`. Quote 150.000 được truyền thẳng cho host, host tự trừ phần đã hoàn → ledger 120.000, reply "đã hoàn 120.000đ", Lab 8 PASS |
| Regression test | `src/tests/test_lab9_trace_case.py`. `test_lab9_trace_case_pre_deducted_is_caught` assert ledger 90.000, có event `proposal`, `RefundAmountCorrect` và `ReplyMatchesLedger` cùng False trên `seeded_regression`. `test_lab9_trace_case_fixed_passes` assert cả hai True và ledger 120.000 trên `fixed`. Đã chạy: fail đúng trên variant lỗi, pass trên `fixed` |
| Chưa chắc chắn | Trace không ghi kết quả host trả về, nên con số "host trừ thêm 30.000" là suy ra từ ledger (90.000 = 120.000 − 30.000) và luật trần theo đơn, không đọc trực tiếp từ event. Case chỉ chứng minh trên MockLLM với seed 11; variant bật lỗi ở mọi seed |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
