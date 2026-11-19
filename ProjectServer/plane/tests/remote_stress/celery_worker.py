"""Isolated mixed-test worker process; never referenced by production entrypoints."""
import argparse
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--queue',choices=['diagnostics','field-repairs'],required=True)
    parser.add_argument('--concurrency',type=int,required=True)
    parser.add_argument('--ready-file',required=True)
    args=parser.parse_args()
    if not os.environ.get('REMOTE_STRESS_BROKER') or not 1<=args.concurrency<=4:
        raise ValueError('explicit isolated broker and bounded concurrency required')
    import django
    django.setup()
    from plane.celery import app
    from celery.signals import worker_ready
    from plane.quality import remote_tasks
    remote_tasks.provider_config=lambda _: {'configured':True}
    app.conf.update(broker_url=os.environ['REMOTE_STRESS_BROKER'],worker_prefetch_multiplier=1)
    @worker_ready.connect
    def ready(**_kwargs):
        Path(args.ready_file).touch()
    app.worker_main(['worker','--pool=threads','--concurrency='+str(args.concurrency),
        '--queues='+args.queue,'--hostname='+args.queue+'@%h','--loglevel=ERROR',
        '--without-gossip','--without-mingle','--without-heartbeat'])


if __name__=='__main__':
    main()
