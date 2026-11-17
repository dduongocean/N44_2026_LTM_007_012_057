Lần chạy kiểm thử chấp nhận NET-02 bằng tay (2026-11-17 ~23:19–23:22), KHÔNG dùng cho biên bản cuối.
Thay bằng loạt chạy lại bằng tools/run_net02_acceptance.sh (3 trường hợp × 3 lần × 60 s).
- summary có 3 dòng đầu rx = 0 (lần chạy hỏng, nguyên nhân không xác định; file raw đã bị ghi đè – BUG-03).
- 3 lần đo hợp lệ: acc_ref 0.00% / RTT 10.95 ms; acc_loss10 9.78%; acc_delay50 RTT 60.50 ms (+49.55 ms),
  76 bản tin "mất" kèm 21 resync do gói đến sai thứ tự (xác nhận trên data/pcap/net-01-tap-gcs-full.pcap, 23:21:37–23:22:37).
