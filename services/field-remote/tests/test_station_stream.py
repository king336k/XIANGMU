import sys,json,queue,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from station_stream import StationStream,websocket_module

class StreamTests(unittest.TestCase):
    def test_vendor_is_local_and_importable_without_system_install(self):
        self.assertEqual(websocket_module().__version__,'1.8.0')

    def test_close_frame_is_not_parsed_as_json(self):
        stream=StationStream.__new__(StationStream);stream.api=websocket_module();stream.socket=Mock()
        stream.stopping=threading.Event();stream.failed=threading.Event();stream.failure_kind='';stream.messages=queue.Queue()
        stream.socket.recv_data.return_value=(stream.api.ABNF.OPCODE_CLOSE,(1001).to_bytes(2,'big'))
        stream.receive();self.assertEqual(stream.failure_kind,'close_1001');self.assertTrue(stream.failed.is_set())

    def test_confirmed_batch_is_removed_only_after_matching_ack(self):
        stream=StationStream.__new__(StationStream);stream.failed=threading.Event();stream.messages=queue.Queue();stream.seq=1;stream.pending=(2,3);stream.sent_at=time.monotonic();stream.inflight=[(1,2,3,stream.sent_at)];stream.reserved_outputs=2;stream.reserved_results=3;stream.failure_kind=''
        engine=Mock();stream.messages.put({'type':'exchange','seq':1,'commands':[{'id':'command'}]})
        stream.poll(engine)
        engine.acknowledge.assert_called_once_with(2,3);engine.accept.assert_called_once_with({'id':'command'});self.assertIsNone(stream.pending)

    def test_reconnect_never_discards_unconfirmed_output(self):
        stream=StationStream.__new__(StationStream);stream.failed=threading.Event();stream.messages=queue.Queue();stream.pending=(1,1);stream.seq=1;stream.sent_at=time.monotonic()-10;stream.inflight=[(1,1,1,stream.sent_at)];stream.failure_kind=''
        engine=Mock()
        with self.assertRaises(OSError):stream.poll(engine)
        engine.acknowledge.assert_not_called()

    def test_no_second_send_before_ack_and_credentials_not_in_frames(self):
        stream=StationStream.__new__(StationStream);stream.pending=None;stream.seq=0;stream.socket=Mock();stream.inflight=[];stream.reserved_outputs=0;stream.reserved_results=0
        self.assertTrue(stream.send({'username':'real'},[{'id':'out'}],[]));self.assertFalse(stream.send({},[{'id':'out'}],[]))
        payload=json.loads(stream.socket.send.call_args.args[0]);self.assertEqual(payload['seq'],1);self.assertNotIn('token',str(payload))

    def test_pipeline_can_flush_new_output_before_previous_batch_ack_without_duplicates(self):
        stream=StationStream.__new__(StationStream);stream.socket=Mock();stream.inflight=[];stream.pending=None;stream.seq=0;stream.reserved_outputs=0;stream.reserved_results=0;stream.failed=threading.Event();stream.messages=queue.Queue();stream.failure_kind=''
        a={'id':'a'};b={'id':'b'};engine=Mock()
        self.assertTrue(stream.send({},[a],[]));self.assertTrue(stream.send({},[a,b],[]))
        messages=[json.loads(c.args[0])for c in stream.socket.send.call_args_list]
        self.assertEqual(messages[0]['payload']['outputs'],[a]);self.assertEqual(messages[1]['payload']['outputs'],[b])
        stream.messages.put({'type':'exchange','seq':1,'commands':[]});stream.messages.put({'type':'exchange','seq':2,'commands':[]});stream.poll(engine)
        self.assertEqual(engine.acknowledge.call_count,2);self.assertEqual(stream.reserved_outputs,0);self.assertIsNone(stream.pending)

if __name__=='__main__':unittest.main()
