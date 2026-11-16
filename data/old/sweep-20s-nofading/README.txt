Loạt NET-03 đầu tiên (2026-11-16/18), KHÔNG dùng cho báo cáo chính – giữ để so sánh "không fading".
Cấu hình: rover-wifi.cc trước khi thêm fading (LogDistance exponent 3, ReferenceLoss mặc định 46.68 dB, không fading).
Vấn đề: mỗi lần 20 s (AC1 cần 60 s); không có baseline localhost; d010_r1 ghi 2 lần; có 3 dòng test_* của NET-02.
Kết quả: 10–50 m mất ~1.3%, từ 60 m mất 100% – đứt gọn tại ≈ 51.4 m (công suất thu = -82 dBm).
net-03-wifi-50m.pcap: pcap 802.11 ở 50 m của NET-03/T4 với cấu hình này (6 khung Retry / 26 528 khung dữ liệu).
Xem docs/experiments/calibration.txt mục 6.
