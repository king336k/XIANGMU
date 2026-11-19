"""Outbound authenticated WebSocket; commands still use the existing Engine and expiry policy."""
import importlib.util
import json
from pathlib import Path
import queue
import threading
import time
from urllib.parse import urlsplit, urlunsplit


def websocket_module():
    package=Path(__file__).with_name('vendor')/'websocket'
    spec=importlib.util.spec_from_file_location('engram_websocket_vendor',package/'__init__.py',submodule_search_locations=[str(package)])
    import sys
    module=sys.modules.get(spec.name)
    if module is None:
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


class StationStream:
    def __init__(self,server,token):
        self.api=websocket_module()
        parsed=urlsplit(server)
        url=urlunsplit(('wss'if parsed.scheme=='https'else'ws',parsed.netloc,
            parsed.path.rstrip('/')+'/api/quality-auth/remote-diagnostics/station-stream/','',''))
        try:
            self.socket=self.api.create_connection(url,header=['Authorization: Bearer '+token],
                suppress_origin=True,timeout=5,enable_multithread=True,http_proxy_host=None,http_proxy_port=None,http_no_proxy=['*'])
            first=json.loads(self.socket.recv())
            if first!={'type':'ready'}:
                self.socket.close();raise ValueError('invalid_station_stream_handshake')
            self.socket.settimeout(None)
        except Exception:
            if hasattr(self,'socket'):
                try:self.socket.close()
                except Exception:pass
            raise OSError('station_stream_upgrade_failed')
        self.messages=queue.Queue(maxsize=100)
        self.stopping=threading.Event();self.failed=threading.Event();self.failure_kind=""
        self.pending=None;self.seq=0;self.sent_at=0;self.last_roundtrip_ms=0
        self.inflight=[];self.reserved_outputs=0;self.reserved_results=0
        self.receiver=threading.Thread(target=self.receive,daemon=True);self.receiver.start()

    def receive(self):
        while not self.stopping.is_set():
            try:
                opcode,raw=self.socket.recv_data()
                if opcode==self.api.ABNF.OPCODE_CLOSE:
                    self.failure_kind='close_'+str(int.from_bytes(raw[:2],'big')if len(raw)>=2 else 1000)
                    self.failed.set();return
                if isinstance(raw,bytes):raw=raw.decode('utf-8')
                if not isinstance(raw,str)or len(raw)>1500000:raise ValueError('invalid_stream_frame')
                message=json.loads(raw)
                if not isinstance(message,dict)or message.get('type')not in{'exchange','commands'}:raise ValueError('invalid_stream_message')
                self.messages.put_nowait(message)
            except self.api.WebSocketTimeoutException:continue
            except Exception as error:
                self.failure_kind=type(error).__name__
                self.failed.set();return

    def poll(self,engine):
        if self.failed.is_set() or self.inflight and time.monotonic()-self.inflight[0][3]>8:
            reason=self.failure_kind or 'ack_timeout'
            raise OSError('station_stream_'+reason)
        while True:
            try:message=self.messages.get_nowait()
            except queue.Empty:return
            if message['type']=='exchange':
                if not self.inflight or message.get('seq')!=self.inflight[0][0]:raise ValueError('invalid_stream_ack')
                seq,outputs,results,sent_at=self.inflight.pop(0)
                self.reserved_outputs-=outputs;self.reserved_results-=results
                self.pending=(self.inflight[0][1],self.inflight[0][2]) if self.inflight else None
                self.last_roundtrip_ms=round((time.monotonic()-sent_at)*1000,1)
                engine.acknowledge(outputs,results);engine.last_exchange=time.monotonic()
            commands=message.get('commands')
            if not isinstance(commands,list)or len(commands)>100:raise ValueError('invalid_stream_commands')
            for command in commands:
                if isinstance(command,dict):engine.accept(command)

    def send(self,identity,outputs,results):
        if len(self.inflight)>=4:return False
        outputs=outputs[self.reserved_outputs:];results=results[self.reserved_results:]
        if self.inflight and not outputs and not results:return False
        self.seq+=1;self.sent_at=time.monotonic()
        self.inflight.append((self.seq,len(outputs),len(results),self.sent_at))
        self.reserved_outputs+=len(outputs);self.reserved_results+=len(results)
        self.pending=(self.inflight[0][1],self.inflight[0][2])
        try:self.socket.send(json.dumps({'seq':self.seq,'payload':{'identity':identity,'outputs':outputs,'results':results}}))
        except Exception:raise OSError('station_stream_send_failed')
        return True

    def close(self):
        self.stopping.set()
        try:self.socket.close(timeout=1)
        except Exception:pass
        self.receiver.join(timeout=2)
