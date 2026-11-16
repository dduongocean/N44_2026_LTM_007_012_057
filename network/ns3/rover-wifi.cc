/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * NET-01/T2: rover-wifi.cc
 * Chương trình mô phỏng Wi-Fi ad-hoc 802.11g giữa 2 node (tap-gcs <-> tap-rover)
 * sử dụng TapBridge ở chế độ UseLocal trong ns-3.
 *
 * Người thực hiện: Vũ Duy Dương (NET-01/T2)
 */

#include "ns3/core-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/tap-bridge-module.h"
#include "ns3/wifi-module.h"

#include <iomanip>
#include <iostream>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("RoverWifi");

// MAC của veth-gcs / veth-rover trong netns, PHẢI trùng với GCS_MAC / ROVER_MAC trong network/setup-netns.sh.
static const char* GCS_MAC = "02:00:00:00:00:01";
static const char* ROVER_MAC = "02:00:00:00:00:02";

/*
 * Gán MAC cho thiết bị Wi-Fi ở CẢ WifiMac lẫn FrameExchangeManager (BUG-01).
 * TapBridge UseLocal gọi NetDevice::SetAddress(MAC của veth) khi nhận khung đầu tiên từ tap;
 * WifiNetDevice::SetAddress chỉ đổi WifiMac, không đổi FrameExchangeManager, nên khung gửi đi có
 * TA không khớp link nào -> NS_ASSERT linkId.has_value() trong WifiMacQueueSchedulerImpl.
 * Gán sẵn đúng MAC đó trước khi chạy thì lệnh SetAddress của TapBridge không đổi gì nữa.
 */
static void
SetWifiAddress(Ptr<NetDevice> device, Mac48Address address)
{
    Ptr<WifiNetDevice> wifiDevice = DynamicCast<WifiNetDevice>(device);
    NS_ABORT_MSG_IF(!wifiDevice, "Thiết bị không phải WifiNetDevice");
    wifiDevice->GetMac()->SetAddress(address);
    wifiDevice->GetMac()->GetFrameExchangeManager()->SetAddress(address);
}

int
main(int argc, char* argv[])
{
    // Giá trị tham số mặc định theo đặc tả NET-01/T2
    double distance = 5.0;                      // Khoảng cách (m), node 0 ở gốc, node 1 ở distance
    double simTime = 3600.0;                    // Thời gian mô phỏng (giây)
    std::string phyMode("ErpOfdmRate6Mbps");    // Chế độ PHY (DataMode, ControlMode, NonUnicastMode)
    double txPower = 16.0;                      // Công suất phát (dBm)
    double exponent = 3.0;                      // Hệ số suy hao khoảng cách LogDistance
    double refLoss = 40.046;                    // Suy hao ở mốc 1 m (dB) cho 2.412 GHz: 20log10(4*pi*1m/lambda)
    bool fading = true;                         // Fading Nakagami: mất gói tăng dần thay vì đứt gọn ở một khoảng cách
    double fadingM = 1.5;                       // Tham số m của Nakagami (m=1: Rayleigh; m càng lớn càng ít dao động)
    bool pcap = false;                          // Bật bắt gói PCAP radiotap ra data/pcap/

    CommandLine cmd(__FILE__);
    cmd.AddValue("distance", "Khoang cach giua node 0 va node 1 (m)", distance);
    cmd.AddValue("simTime", "Thoi gian mo phong (s)", simTime);
    cmd.AddValue("phyMode", "Che do toc do 802.11g PHY", phyMode);
    cmd.AddValue("txPower", "Cong suat phat (dBm)", txPower);
    cmd.AddValue("exponent", "He so suy hao LogDistancePropagationLossModel", exponent);
    cmd.AddValue("refLoss", "Suy hao o moc 1 m cua LogDistance (dB), 40.046 cho 2.412 GHz", refLoss);
    cmd.AddValue("fading", "Bat fading NakagamiPropagationLossModel", fading);
    cmd.AddValue("fadingM", "Tham so m cua Nakagami (dung chung cho moi khoang cach)", fadingM);
    cmd.AddValue("pcap", "Bat bat goi pcap 802.11 ra data/pcap/", pcap);
    cmd.Parse(argc, argv);

    // In toàn bộ giá trị tham số cấu hình ra màn hình để ghi vào log thí nghiệm
    std::cout << "================ Mô phỏng ns-3 Wi-Fi TapBridge ================" << std::endl;
    std::cout << " Khoảng cách     : " << distance << " m" << std::endl;
    std::cout << " Thời gian chạy  : " << simTime << " s" << std::endl;
    std::cout << " Chế độ PHY      : " << phyMode << std::endl;
    std::cout << " Công suất phát  : " << txPower << " dBm" << std::endl;
    std::cout << " Hệ số suy hao   : " << exponent << std::endl;
    std::cout << " Suy hao mốc 1 m : " << refLoss << " dB" << std::endl;
    std::cout << " Fading Nakagami : " << (fading ? "Bật, m = " + std::to_string(fadingM) : std::string("Tắt"))
              << std::endl;
    std::cout << " RngRun          : " << RngSeedManager::GetRun() << std::endl;
    std::cout << " Bắt gói PCAP    : " << (pcap ? "Bật (data/pcap/)" : "Tắt") << std::endl;
    std::cout << " Cổng TAP ảo     : tap-gcs (Node 0) <---> tap-rover (Node 1)" << std::endl;
    std::cout << " Chế độ TapBridge: UseLocal (RealtimeSimulator)" << std::endl;
    std::cout << "================================================================" << std::endl;

    // Bắt buộc dùng RealtimeSimulator và tính Checksum khi kết nối với Linux kernel thật
    GlobalValue::Bind("SimulatorImplementationType", StringValue("ns3::RealtimeSimulatorImpl"));
    GlobalValue::Bind("ChecksumEnabled", BooleanValue(true));

    // Cố định tốc độ gói non-unicast (như ARP broadcast) bằng tốc độ dữ liệu unicast
    Config::SetDefault("ns3::WifiRemoteStationManager::NonUnicastMode", StringValue(phyMode));

    // Tạo 2 ghost node
    NodeContainer nodes;
    nodes.Create(2);

    // Cấu hình kênh truyền: độ trễ truyền sóng và mô hình suy hao khoảng cách LogDistance
    YansWifiChannelHelper channel;
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel",
                               "Exponent", DoubleValue(exponent),
                               "ReferenceLoss", DoubleValue(refLoss));
    // Fading nhanh: mỗi khung nhận thêm một hệ số công suất ngẫu nhiên Gamma(m, 1/m) quanh giá trị LogDistance.
    // Không có fading thì công suất thu cố định theo khoảng cách; mô hình phát hiện preamble của ns-3
    // (MinimumRssi -82 dBm) cắt liên lạc gọn tại một khoảng cách (mất gói chỉ 0% hoặc 100%).
    // Xem docs/experiments/calibration.txt mục 6.
    if (fading)
    {
        channel.AddPropagationLoss("ns3::NakagamiPropagationLossModel",
                                   "m0", DoubleValue(fadingM),
                                   "m1", DoubleValue(fadingM),
                                   "m2", DoubleValue(fadingM));
    }

    // Cấu hình tầng vật lý (PHY)
    YansWifiPhyHelper phy;
    phy.SetChannel(channel.Create());
    phy.Set("TxPowerStart", DoubleValue(txPower));
    phy.Set("TxPowerEnd", DoubleValue(txPower));

    if (pcap)
    {
        phy.SetPcapDataLinkType(WifiPhyHelper::DLT_IEEE802_11_RADIO);
    }

    // Cấu hình tầng MAC và chuẩn Wi-Fi 802.11g Ad-hoc
    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211g);
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                 "DataMode", StringValue(phyMode),
                                 "ControlMode", StringValue(phyMode));

    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");

    // Gắn thiết bị Wi-Fi vào 2 ghost node
    NetDeviceContainer devices = wifi.Install(phy, mac, nodes);

    // Gán sẵn MAC trùng với veth trong netns (xem SetWifiAddress, BUG-01)
    SetWifiAddress(devices.Get(0), Mac48Address(GCS_MAC));
    SetWifiAddress(devices.Get(1), Mac48Address(ROVER_MAC));

    // Cấu hình vị trí cố định: Node 0 tại (0, 0, 0), Node 1 tại (distance, 0, 0)
    MobilityHelper mobility;
    Ptr<ListPositionAllocator> positionAlloc = CreateObject<ListPositionAllocator>();
    positionAlloc->Add(Vector(0.0, 0.0, 0.0));
    positionAlloc->Add(Vector(distance, 0.0, 0.0));
    mobility.SetPositionAllocator(positionAlloc);
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(nodes);

    // Ghi file pcap nếu bật cờ pcap
    if (pcap)
    {
        phy.EnablePcap("data/pcap/rover-wifi", devices);
    }

    // Cấu hình TapBridge chế độ UseLocal nối tap trên host vào mô phỏng ns-3
    TapBridgeHelper tapBridge;
    tapBridge.SetAttribute("Mode", StringValue("UseLocal"));

    // Node 0 nối với tap-gcs (phía trạm mặt đất)
    tapBridge.SetAttribute("DeviceName", StringValue("tap-gcs"));
    tapBridge.Install(nodes.Get(0), devices.Get(0));

    // Node 1 nối với tap-rover (phía xe rover PX4)
    tapBridge.SetAttribute("DeviceName", StringValue("tap-rover"));
    tapBridge.Install(nodes.Get(1), devices.Get(1));

    // Chạy mô phỏng
    Simulator::Stop(Seconds(simTime));
    Simulator::Run();
    Simulator::Destroy();

    return 0;
}
