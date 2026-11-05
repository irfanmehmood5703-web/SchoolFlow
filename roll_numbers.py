"""Opt-in admission roll series, allocated under the institute write gate."""
import hashlib,hmac,json,re
from datetime import datetime,timezone
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from itsdangerous import BadData,URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

MAX_NUMBER=999999999999

def configure_roll_numbers(app,db,Student):
    bp=Blueprint('roll_numbers',__name__,url_prefix='/workspace/core/roll-number-series')
    models=app.extensions['school_settings_models'];Config=models['setting'];Item=models['item'];rm=app.extensions['record_models'];Details=rm['student'];Audit=app.extensions['ops_models']['audit']
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    def key(scope):return digest(list(scope))
    def config():return db.session.get(Config,'roll-numbers')
    def rules():return Item.query.filter_by(kind='roll-series').order_by(Item.id).all()
    def controls():
        row=config();return {**dict(enabled=False,skip=True,imports=False),**(row.data if row else {})}
    def roster():
        return [(s,d) for s,d in db.session.query(Student,Details).join(Details,Details.student_id==Student.id).order_by(Student.id).all()]
    def scope_of(row):return row.scope,row.data.get('class_name',''),row.data.get('section','')
    def roll_value(data):
        value=data.get('roll_no')
        return '' if value is None else str(value).strip()
    def matches(scope,s,data):return all(not value or value==actual for value,actual in zip(scope,(data.get('campus',''),s.class_name,data.get('section',''))))
    def scopes():
        values={cat:sorted({r.value for r in rm['settings'].query.filter_by(category=cat).all()}) for cat in ('campus','class_name','section')}
        result={('','','')}
        maps=app.extensions['institute_setup_models']['mapping'].query.all()
        for campus in values['campus']:
            result.add((campus,'',''))
            linked=[m for m in maps if m.campus==campus]
            offerings=[(m.class_name,m.data.get('sections',[])) for m in linked] if linked else [(c,values['section']) for c in values['class_name']]
            for cls,sections in offerings:
                result.add((campus,cls,''))
                for section in sections:result.add((campus,cls,section))
        result.update(scope_of(r) for r in rules())
        return sorted(result)
    class Allocator:
        def __init__(self,imports=False):
            self.cfg=controls();self.enabled=self.cfg['enabled'] and (not imports or self.cfg['imports']);self.rows=rules();self.people=roster();self.next={r.id:r.data.get('next',r.data.get('start')) for r in self.rows};self.reserved=[];self.changed=set()
            cfg=config();self.stamp=digest([cfg.version if cfg else 0,self.cfg,[[r.id,r.version,r.data] for r in self.rows],[[s.id,s.class_name,s.status,d.data] for s,d in self.people]])
        def select(self,data):
            candidates=[r for r in self.rows if r.data.get('start') is not None and all(not v or v==data.get(k,'') for v,k in zip(scope_of(r),('campus','class_name','section')))]
            return max(candidates,key=lambda r:sum(bool(x) for x in scope_of(r)),default=None)
        def numeric_used(self,row):
            prefix=row.data.get('prefix','');scope=scope_of(row);used=set()
            values=[str(d.data.get('roll_no','')).strip() for s,d in self.people if matches(scope,s,d.data)]
            values.extend(str(data.get('roll_no','')).strip() for data in self.reserved if all(not v or v==data.get(k,'') for v,k in zip(scope,('campus','class_name','section'))))
            for value in values:
                tail=value[len(prefix):] if value.startswith(prefix) else ''
                if re.fullmatch(r'[0-9]{1,12}',tail):used.add(int(tail))
            return used
        def allocate(self,data,force=False):
            if roll_value(data):self.reserved.append(dict(data));return
            if (not self.enabled and not force) or data.get('status') not in ('Active','Waiting'):return
            row=self.select(data)
            if not row:return
            number=self.next[row.id];used=self.numeric_used(row) if self.cfg['skip'] else set()
            while number in used:number+=1
            if number>MAX_NUMBER:raise ValueError('This roll-number series is exhausted. Configure a new range.')
            data['roll_no']=row.data.get('prefix','')+str(number).zfill(row.data.get('digits',0));self.next[row.id]=number+1;self.changed.add(row.id);self.reserved.append(dict(data))
        def persist(self):
            for row in self.rows:
                if row.id in self.changed:row.data={**row.data,'next':self.next[row.id]}
    def assign(data):
        alloc=Allocator();alloc.allocate(data);alloc.persist()
    app.extensions['roll_number_helpers']=dict(allocator=Allocator,assign=assign,controls=controls)
    def signer():return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-fill-roll-blanks-v1')
    def actor():return [session.get('owner_id'),session.get('record_csrf'),(getattr(g,'school_identity',None) or {}).get('scope')]
    def fill(scope):
        alloc=Allocator()
        if not alloc.cfg['enabled']:raise ValueError('Enable and save automatic roll numbering before filling blanks.')
        changes=[]
        for pupil,detail in alloc.people:
            if len(changes)>=200:break
            if pupil.status not in ('Active','Waiting') or not matches(scope,pupil,detail.data) or roll_value(detail.data):continue
            data={**detail.data,'class_name':pupil.class_name,'status':pupil.status};alloc.allocate(data)
            if data.get('roll_no'):changes.append(dict(id=pupil.id,name=pupil.name,roll=data['roll_no']))
        return alloc,changes
    @bp.before_request
    def protect():
        if request.method=='POST':
            if not request.form.get('_csrf') or not hmac.compare_digest(request.form['_csrf'],session.get('record_csrf','')):abort(400,'Reload this form.')
            app.extensions['admission_capacity']['lock']()
    @bp.errorhandler(ValueError)
    def invalid(error):db.session.rollback();return render_template('operation_error.html',title='Check roll series',error=str(error)),422
    @bp.errorhandler(IntegrityError)
    @bp.errorhandler(StaleDataError)
    def conflict(error):db.session.rollback();return render_template('operation_error.html',title='Check roll series',error='The series changed. Reload and review again.'),422
    @bp.route('',methods=['GET','POST'])
    def index():
        available={key(s):s for s in scopes()};cfg=config()
        if request.method=='POST':
            action=request.form.get('action')
            if action=='settings':
                if request.form.get('version')!=str(cfg.version if cfg else 0):raise ValueError('Settings changed. Reload first.')
                data={k:request.form.get(k)=='1' for k in ('enabled','skip','imports')}
                if cfg:cfg.data=data
                else:db.session.add(Config(key='roll-numbers',data=data))
            elif action=='series':
                keys=request.form.getlist('series_key');lookup={key(scope_of(r)):r for r in rules()}
                if not keys or len(keys)>50 or len(set(keys))!=len(keys) or any(k not in available for k in keys):raise ValueError('Choose the displayed series rows.')
                for k in keys:
                    row=lookup.get(k);scope=available[k]
                    if request.form.get('version_'+k)!=str(row.version if row else 0):raise ValueError('A series changed. Reload before saving.')
                    prefix=request.form.get('prefix_'+k,'').strip();raw=request.form.get('start_'+k,'').strip();digits=request.form.get('digits_'+k,'0')
                    if len(prefix)>30 or any(ord(c)<32 for c in prefix):raise ValueError('Use a prefix up to 30 printable characters.')
                    if not re.fullmatch(r'[0-9]{1,2}',digits) or not 0<=int(digits)<=12:raise ValueError('Digits must be 0–12.')
                    if raw and (not re.fullmatch(r'[0-9]{1,12}',raw) or int(raw)>MAX_NUMBER):raise ValueError('Start at must be a whole number up to 12 digits, or blank to disable.')
                    start=int(raw) if raw else None
                    same=row and all(row.data.get(field)==v for field,v in [('start',start),('prefix',prefix),('digits',int(digits))])
                    data=dict(class_name=scope[1],section=scope[2],prefix=prefix,start=start,digits=int(digits),next=row.data.get('next',start) if same else start)
                    if row:row.data=data
                    elif start is not None or prefix:db.session.add(Item(kind='roll-series',scope=scope[0],name=k,data=data))
            elif action=='fill':
                raw=request.form.get('review','')
                if len(raw)>8192:raise ValueError('Invalid roll review.')
                try:payload=signer().loads(raw,max_age=900)
                except BadData:raise ValueError('Review the current blank rolls before applying.')
                scope=available.get(payload.get('key'))
                if scope is None:raise ValueError('This scope changed.')
                alloc,changes=fill(scope)
                if payload!=dict(actor=actor(),key=key(scope),stamp=alloc.stamp,changes=digest(changes)):raise ValueError('The series or students changed. Review again.')
                if not changes:raise ValueError('No blank roll numbers remain in this selection.')
                for change in changes:
                    detail=Details.query.filter_by(student_id=change['id']).one();detail.data={**detail.data,'roll_no':change['roll']};detail.updated_at=datetime.now(timezone.utc)
                    db.session.add(rm['event'](owner_kind='student',owner_id=change['id'],action='Assigned roll number'))
                alloc.persist()
            else:raise ValueError('Choose a valid roll-series action.')
            db.session.add(Audit(action='Save roll-number '+action,data=dict(owner_id=session.get('owner_id'),changes=changes if action=='fill' else [])));db.session.commit();flash('Roll-number settings saved. Existing typed roll numbers are retained.','success');return redirect(url_for('roll_numbers.index'))
        alloc=Allocator();lookup={key(scope_of(r)):r for r in alloc.rows};all_scopes=list(available.items());page=max(1,request.args.get('p',1,type=int));pages=max(1,(len(all_scopes)+49)//50);page=min(page,pages);display=[]
        for k,scope in all_scopes[(page-1)*50:page*50]:
            from types import SimpleNamespace
            row=lookup.get(k);used=alloc.numeric_used(row or SimpleNamespace(scope=scope[0],data=dict(class_name=scope[1],section=scope[2],prefix='')))
            highest=max(used) if used else None;number=alloc.next[row.id] if row else None
            if number is not None and alloc.cfg['skip']:
                while number in used:number+=1
            nxt=(row.data.get('prefix','')+str(number).zfill(row.data.get('digits',0))) if number is not None and number<=MAX_NUMBER else '—'
            display.append(dict(key=k,scope=scope,row=row,next=nxt,highest=highest))
        preview=[];token=''
        if request.args.get('fill'):
            scope=available.get(request.args['fill'])
            if scope is None:abort(404)
            alloc,preview=fill(scope);token=signer().dumps(dict(actor=actor(),key=key(scope),stamp=alloc.stamp,changes=digest(preview)))
        return render_template('roll_numbers.html',title='Roll Number Series',cfg=cfg,controls=controls(),rows=display,page=page,pages=pages,preview=preview,review=token)
    app.register_blueprint(bp)
