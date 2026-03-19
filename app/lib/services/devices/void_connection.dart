import 'dart:async';
import 'package:omi/backend/schema/bt_device/bt_device.dart';
import 'package:omi/services/devices/device_connection.dart';
import 'package:omi/services/devices/models.dart';

const String voidAudioServiceUuid = '19b10000-e8f2-537e-4f6c-d104768a1214';
const String voidAudioStreamUuid = '19b10001-e8f2-537e-4f6c-d104768a1214';

class VoidConnection extends DeviceConnection {
  VoidConnection(super.device, super.transport);

  @override
  Future<BleAudioCodec> performGetAudioCodec() async {
    return BleAudioCodec.pcm16; 
  }

  @override
  Future<StreamSubscription?> performGetBleAudioBytesListener({
    required void Function(List<int> p1) onAudioBytesReceived,
  }) async {
    final stream = transport.getCharacteristicStream(
      voidAudioServiceUuid,
      voidAudioStreamUuid,
    );
    return stream.listen(onAudioBytesReceived);
  }

  // 🚀 --- REQUIRED DUMMY OVERRIDES FOR COMPILATION --- 🚀
  @override
  Future<void> performCameraStartPhotoController() async {}

  @override
  Future<void> performCameraStopPhotoController() async {}

  // 🛠️ FIXED: Exact parameter names from the Omi base class
  @override
  Future<StreamSubscription<List<int>>?> performGetAccelListener({dynamic onAccelChange}) async => null;

  @override
  Future<StreamSubscription?> performGetBleStorageBytesListener({dynamic onStorageBytesReceived}) async => null;

  @override
  Future<List<int>> performGetButtonState() async => [];

  @override
  Future<int> performGetFeatures() async => 0;

  // 🛠️ FIXED: Exact parameter name
  @override
  Future<StreamSubscription?> performGetImageListener({dynamic onImageReceived}) async => null;

  @override
  Future<int?> performGetLedDimRatio() async => null;

  @override
  Future<int?> performGetMicGain() async => null;

  @override
  Future<bool> performHasPhotoStreamingCharacteristic() async => false;

  @override
  Future<int> performRetrieveBatteryLevel() async => 100; 

  @override
  Future<void> performSetLedDimRatio(int ratio) async {}

  @override
  Future<void> performSetMicGain(int gain) async {}
}