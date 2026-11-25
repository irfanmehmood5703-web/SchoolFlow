"""Device-authenticated, paced snapshots for explicitly started school-SIM runs."""
import math,re,time
from collections import Counter
from flask import abort,jsonify

def configure_sms_batches(app,db,bp,Device,Job,auth,data):
    class Batch(db.Model):
        __tablename__='sms_send_batch'
        id=db.Column(db.String(43),primary_key=True)
        device_id=db.Column(db.Integer,db.ForeignKey(Device.id),nullable=False,index=True)
        generation=db.Column(db.Integer,nullable=False)
        interval=db.Column(db.Integer,nullable=False)
        jobs=db.Column(db.JSON,nullable=False)
        active=db.Column(db.Boolean,nullable=False,default=True)
        created=db.Column(db.Float,nullable=False,default=time.time)
    class Pace(db.Model):
        __tablename__='sms_send_pace'
        device_id=db.Column(db.Integer,db.ForeignKey(Device.id),primary_key=True)
        next_at=db.Column(db.Float,nullable=False,default=0)
        interval=db.Column(db.Integer,nullable=False,default=20)
    app.extensions['sms_models'].update(batch=Batch,pace=Pace)
    def owned(device,raw):
        if not isinstance(raw,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',raw):abort(422)
        row=db.get_or_404(Batch,raw)
        if row.device_id!=device.id or row.generation!=device.generation:abort(403)
        return row
    def rows(row):return Job.query.filter(Job.id.in_(row.jobs),Job.device_id==row.device_id,Job.generation==row.generation).all()
    def summary(row):
        counts=Counter(j.state for j in rows(row));pace=db.session.get(Pace,row.device_id)
        return dict(id=row.id,interval=row.interval,active=row.active,total=len(row.jobs),sent=counts['sent'],failed=counts['failed'],unknown=counts['unknown'],started=counts['started'],pending=counts['queued']+counts['claimed'],cancelled=counts['cancelled'],wait_seconds=max(0,math.ceil((pace.next_at if pace else 0)-time.time())))
    def stop(row):
        row.active=False
        for job in rows(row):
            if job.state=='claimed':job.state='queued';job.token='';job.expires=0;job.updated=time.time()
    def selected_ids(payload):
        ids=payload.get('ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=50 or any(not isinstance(i,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',i) for i in ids) or len(set(ids))!=len(ids):abort(422)
        return ids
    def pending(device):
        return Job.query.filter_by(device_id=device.id,generation=device.generation,state='queued')
    @bp.post('/api/sms/devices/<int:did>/pending')
    def pending_list(did):
        device,_=auth(did);data();q=pending(device)
        count=q.count();jobs=q.order_by(Job.created,Job.id).limit(50).all()
        response=dict(total=count,jobs=[dict(id=j.id,phone=j.phone,text=j.text) for j in jobs])
        db.session.commit();return jsonify(**response)
    @bp.post('/api/sms/devices/<int:did>/cancel-pending')
    def cancel_pending(did):
        device,_=auth(did);ids=selected_ids(data())
        if active(device):abort(409,'Pause sending before cancelling messages.')
        jobs=Job.query.filter(Job.id.in_(ids),Job.device_id==device.id,Job.generation==device.generation).all()
        if len(jobs)!=len(ids) or any(j.state not in ('queued','cancelled') for j in jobs):abort(409,'Selection changed. Refresh pending messages.')
        for job in jobs:
            if job.state=='queued':
                job.state='cancelled';job.updated=time.time();job.detail='Cancelled by registered SMS phone operator before submission.'
        db.session.commit();return jsonify(cancelled=len(jobs))
    @bp.post('/api/sms/devices/<int:did>/batch')
    def batch(did):
        device,_=auth(did);payload=data();token=payload.get('id');interval=payload.get('interval',20)
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token) or type(interval) is not int or interval not in (15,20,25):abort(422)
        old=db.session.get(Batch,token)
        if old:
            row=owned(device,token)
            if row.interval!=interval or ('ids' in payload and set(row.jobs)!=set(selected_ids(payload))):abort(409)
            response=summary(row);db.session.commit();return jsonify(batch=response)
        if Batch.query.filter_by(device_id=device.id,generation=device.generation,active=True).first():abort(409,'Pause the previous run before starting another.')
        # A snapshot never absorbs newly queued messages without another Start.
        q=pending(device)
        if 'ids' in payload:
            ids=selected_ids(payload)
            jobs=q.filter(Job.id.in_(ids)).order_by(Job.created,Job.id).all()
            if len(jobs)!=len(ids):abort(409,'Selection changed. Refresh pending messages.')
        else:jobs=q.order_by(Job.created,Job.id).limit(200).all()
        if not jobs:db.session.commit();return jsonify(batch=None,queued=0)
        row=Batch(id=token,device_id=device.id,generation=device.generation,interval=interval,jobs=[j.id for j in jobs]);db.session.add(row);db.session.flush();response=summary(row);db.session.commit();return jsonify(batch=response)
    @bp.post('/api/sms/devices/<int:did>/batch-status')
    def batch_status(did):
        device,_=auth(did);row=owned(device,data().get('batch'));response=summary(row);db.session.commit();return jsonify(batch=response)
    @bp.post('/api/sms/devices/<int:did>/batch-stop')
    def batch_stop(did):
        device,_=auth(did);row=owned(device,data().get('batch'));stop(row);response=summary(row);db.session.commit();return jsonify(batch=response)
    def for_claim(device,payload):
        raw=payload.get('batch')
        if raw is None:
            if Batch.query.filter_by(device_id=device.id,generation=device.generation,active=True).first():abort(409,'A paced run owns this phone queue.')
            return None,None
        row=owned(device,raw)
        if not row.active:return row,dict(job=None,batch=summary(row),paused=True)
        if any(j.state in ('started','unknown','failed') for j in rows(row)):
            stop(row);return row,dict(job=None,batch=summary(row),paused=True,reason='Review the uncertain or failed SMS before starting another run.')
        remaining=summary(row)
        if not remaining['pending']:
            row.active=False;remaining['active']=False;return row,dict(job=None,batch=remaining,complete=True)
        if remaining['wait_seconds']:return row,dict(job=None,batch=remaining,wait_seconds=remaining['wait_seconds'])
        return row,None
    def before_start(device,job,payload):
        raw=payload.get('batch');row=owned(device,raw) if raw is not None else None
        active=Batch.query.filter_by(device_id=device.id,generation=device.generation,active=True).first()
        if row:
            if not row.active or job.id not in row.jobs or active and active.id!=row.id:abort(409)
            if any(j.state in ('started','unknown','failed') and j.id!=job.id for j in rows(row)):abort(409)
        elif active:abort(409,'Start this SMS through the active paced run.')
        pace=db.session.get(Pace,device.id);stamp=time.time()
        if pace and pace.next_at>stamp:abort(429,description='Wait before submitting the next SMS.')
        if not pace:pace=Pace(device_id=device.id);db.session.add(pace)
        pace.interval=row.interval if row else 20
        pace.next_at=stamp+pace.interval
    def after_result(device):
        # The acknowledgement follows the real SIM callbacks. Holding the
        # interval again here prevents process restarts or slow start responses
        # from shortening the actual gap between messages. Replays skip this.
        pace=db.session.get(Pace,device.id)
        if pace:pace.next_at=max(pace.next_at,time.time()+pace.interval)
    def active(device):
        row=Batch.query.filter_by(device_id=device.id,generation=device.generation,active=True).first()
        return summary(row) if row else None
    return dict(for_claim=for_claim,before_start=before_start,summary=summary,active=active,after_result=after_result)
