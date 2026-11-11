"""ROS2 synthetic publisher -> real DAQ C++ capture -> real MCAP and diagnostics."""
import os
from pathlib import Path
root=Path("/verification")
os.environ["ENGRAM_DAQ_LOG_DIR"]=str(root/"logs")
os.environ["ENGRAM_CAPTURE_LOG_PREFIX"]=str(root/"logs"/"capture_service")
import json,time
import cv2,numpy as np,rclpy,rosbag2_py
from sensor_msgs.msg import CompressedImage
from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy,HistoryPolicy
from backend.services.capture_service import CaptureServiceClient
from backend.services.diagnostic_bundle_service import DiagnosticBundleService

root.mkdir(exist_ok=True,parents=True)
rclpy.init()
node=rclpy.create_node("isolated_capture_source")
topic="/engramproject/validation/camera/image/compressed"
publisher=node.create_publisher(CompressedImage,topic,QoSProfile(
 reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.VOLATILE,
 history=HistoryPolicy.KEEP_LAST,depth=10))
session=root/"records"/"real-recording-timestamp-fault"
session.mkdir(parents=True,exist_ok=True)
client=CaptureServiceClient({},binary="/capture-build/engram_capture_service",
 socket_path="/tmp/engramproject_capture.sock",realtime_video_enabled=False)
proof={"physical_robot_used":False,"data_source":"ROS2 synthetic sensor publisher","capture":"real C++ CaptureService + MCAP"}
try:
 client.start()
 client.start_recording(bag_uri=str(session/"rosbag"),record_topic_entries=[{
  "topic":topic,"type":"sensor_msgs/msg/CompressedImage","media_type":"color","camera_id":"validation",
  "target_fps":10}],max_cache_size=16*1024*1024,max_bag_size=64*1024*1024)
 deadline=time.monotonic()+10
 while publisher.get_subscription_count()<1 and time.monotonic()<deadline:
  rclpy.spin_once(node,timeout_sec=.05)
 assert publisher.get_subscription_count()>=1,"No capture subscription"
 image=np.zeros((24,32,3),dtype=np.uint8);image[:,:,1]=160
 ok,encoded=cv2.imencode(".jpg",image);assert ok
 stamps=[100_000_000_000,100_100_000_000,100_200_000_000,100_200_000_000,
         100_150_000_000,100_300_000_000,100_400_000_000]
 for timestamp in stamps:
  msg=CompressedImage();msg.header.stamp.sec=timestamp//1_000_000_000
  msg.header.stamp.nanosec=timestamp%1_000_000_000;msg.format="jpeg";msg.data=encoded.tobytes()
  publisher.publish(msg);rclpy.spin_once(node,timeout_sec=.02);time.sleep(.08)
 deadline=time.monotonic()+5
 while client.get_capture_status().get("written",0)<5 and time.monotonic()<deadline:time.sleep(.1)
 client.stop_recording()
 stats=client.get_recording_topic_stats([topic])[topic]
 proof["topic_stats"]=stats
 reader=rosbag2_py.SequentialReader()
 reader.open(rosbag2_py.StorageOptions(uri=str(session/"rosbag"),storage_id="mcap"),rosbag2_py.ConverterOptions("cdr","cdr"))
 count=0
 while reader.has_next():reader.read_next();count+=1
 proof["mcap_messages"]=count
 proof["mcap_files"]=[p.name for p in (session/"rosbag").glob("*.mcap")]
 assert stats["duplicate_image_timestamp_drops"]>=1
 assert stats["backwards_image_timestamp_drops"]>=1
 assert count>=5
 (session/"recording.log").write_text("Actual CaptureService recording statistics:\n"+json.dumps(stats,ensure_ascii=False))
 (root/"version_info.yaml").write_text("version: f4f621c\nvalidation: isolated-ros2\n")
 bundle=DiagnosticBundleService(logs_root=root/"logs",records_root=root/"records",
  version_info_paths=[root/"version_info.yaml"],runtime_summary={"mode":"isolated-ROS2","robot_connected":False},
  max_uncompressed_bytes=2*1024*1024,max_archive_bytes=2*1024*1024).build(hours=24,include_latest_recording_log=True)
 (root/"capture-fault-diagnostics.zip").write_bytes(bundle.archive_path.read_bytes());bundle.cleanup()
 proof["result"]="recorded_with_timestamp_fault_evidence"
finally:
 client.stop()
 node.destroy_node();rclpy.shutdown()
 (root/"capture-fault-proof.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2))
print(json.dumps(proof,ensure_ascii=False))
